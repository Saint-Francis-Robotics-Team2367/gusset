"""
file_jobs.py - turns a naming Plan into the actual list of edits, grouped by
the Fusion FILE each edit has to happen in. Plain Python (unit tested).

Two kinds of edits:
  local edits - components inside the open design. Applied inside the Name
                Parts command, so ONE Ctrl+Z reverts them.
  file jobs   - linked files. Fusion can't open/save files during a command,
                so these run right after the dialog closes. Each touched file
                gets a new saved version (undo = Version History in Fusion).

Order matters: files are processed deepest-first, so a sub-assembly's file
refreshes its links to freshly renamed parts BEFORE it is saved itself.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from .naming_core import KIND_COTS, MAX_DEPTH, CompNode, Plan

log = logging.getLogger("gusset.file_jobs")


@dataclass
class Edit:
    key: str
    old_name: str
    new_name: str
    part_number: str
    description: str
    kind: str
    is_file_root: bool          # root component of its file: name follows the FILE name
    renumber: bool              # False = only a COTS tag changes
    cots_tag: Optional[str] = None
    is_run_top: bool = False    # the assembly this run was started on (tagged "standalone")
    attrs: Dict[str, str] = field(default_factory=dict)   # extra Gusset tags, e.g. {"process": "X-Carve"}


@dataclass
class FileJob:
    file_id: str
    file_name: str
    rename_to: Optional[str] = None
    edits: List[Edit] = field(default_factory=list)
    refresh: bool = False       # update links to child files before saving

    @property
    def label(self) -> str:
        return self.file_name or self.file_id

    @property
    def rename_only(self) -> bool:
        """
        Quick rename can handle this file WITHOUT opening it: every change is just
        the file's own new number (no parts inside to rename, no COTS/Shared/process
        tags to write). Opening + saving is ~8 s per file; renaming is ~0.5 s.
        """
        return bool(self.rename_to) and all(
            e.is_file_root and e.renumber and e.cots_tag is None and not e.attrs for e in self.edits)


@dataclass
class JobPlan:
    local_edits: List[Edit] = field(default_factory=list)
    jobs: List[FileJob] = field(default_factory=list)    # already in run order
    active_rename: Optional[str] = None                   # new name for the open file
    active_file_name: str = ""

    @property
    def needs_after_step(self) -> bool:
        return bool(self.jobs or self.active_rename)


def file_graph(root: CompNode) -> Dict[str, Set[str]]:
    """{file: files linked directly inside it}. "" = the open design."""
    graph: Dict[str, Set[str]] = {"": set()}
    seen: Set[Tuple[str, str]] = set()

    def visit(node: CompNode, owner: str, depth: int) -> None:
        if depth > MAX_DEPTH or (node.key, owner) in seen:
            return
        seen.add((node.key, owner))
        here = owner
        if node.file_id and node.owner_file == node.file_id:   # root of a linked file
            graph.setdefault(owner, set()).add(node.file_id)
            graph.setdefault(node.file_id, set())
            here = node.file_id
        for child in node.children:
            visit(child, here, depth + 1)

    for child in root.children:
        visit(child, "", 1)
    return graph


def _post_order(graph: Dict[str, Set[str]]) -> List[str]:
    """Children before parents. Cycles (shouldn't happen in Fusion) are broken safely."""
    order: List[str] = []
    state: Dict[str, int] = {}

    def visit(file_id: str) -> None:
        if state.get(file_id) == 2:
            return
        if state.get(file_id) == 1:
            log.warning("Link loop at %s; ignoring", file_id)
            return
        state[file_id] = 1
        for child in sorted(graph.get(file_id, ())):
            visit(child)
        state[file_id] = 2
        order.append(file_id)

    visit("")
    for file_id in sorted(graph):
        visit(file_id)
    return order


def build_jobs(plan: Plan, root: CompNode, overrides: Optional[Dict[str, Dict[str, object]]] = None) -> JobPlan:
    overrides = overrides or {}
    result = JobPlan(active_file_name=root.file_name)
    jobs: Dict[str, FileJob] = {}
    file_names: Dict[str, str] = {}

    for p in plan.proposals:
        if p.file_id:
            file_names[p.file_id] = p.file_name
        cots_tag = None
        if "cots" in overrides.get(p.key, {}) and p.depth > 0:
            cots_tag = "true" if p.kind == KIND_COTS else "false"
        if not p.will_change and cots_tag is None:
            continue
        is_file_root = bool(p.file_id) and (p.file_id == p.owner_file or (p.depth == 0 and not p.owner_file))
        edit = Edit(
            key=p.key, old_name=p.old_name, new_name=p.new_name, part_number=p.part_number,
            description=p.description, kind=p.kind, is_file_root=is_file_root,
            renumber=p.will_change, cots_tag=cots_tag, is_run_top=(p.depth == 0),
        )
        if not p.owner_file:
            result.local_edits.append(edit)
            if is_file_root and p.will_change and p.new_name != p.file_name:
                result.active_rename = p.new_name
            continue
        job = jobs.setdefault(p.owner_file, FileJob(p.owner_file, file_names.get(p.owner_file, "")))
        job.edits.append(edit)
        if is_file_root and p.will_change and p.new_name != p.file_name:
            job.rename_to = p.new_name

    _order_jobs(result, jobs, root, file_names)

    log.info("Jobs: %d local edit(s), %d linked file(s), rename open file: %s",
             len(result.local_edits), len(result.jobs), result.active_rename or "no")
    for job in result.jobs:
        log.debug("  file %-40s edits=%d rename_to=%s refresh=%s",
                  job.label, len(job.edits), job.rename_to, job.refresh)
    return result


def _order_jobs(result: JobPlan, jobs: Dict[str, FileJob], root: CompNode, file_names: Dict[str, str]) -> None:
    """Put file jobs deepest-first, and add refresh jobs for linked files that
    CONTAIN an edited file (they must update their links and be saved too)."""
    graph = file_graph(root)
    order = _post_order(graph)

    def has_job_below(file_id: str, seen: Set[str]) -> bool:
        for child in graph.get(file_id, ()):
            if child in seen:
                continue
            seen.add(child)
            if child in jobs or has_job_below(child, seen):
                return True
        return False

    for file_id in order:
        if file_id and has_job_below(file_id, set()):
            job = jobs.setdefault(file_id, FileJob(file_id, file_names.get(file_id, "")))
            job.refresh = True

    for job in jobs.values():
        if not job.file_name:
            job.file_name = file_names.get(job.file_id, "")
    result.jobs = [jobs[f] for f in order if f in jobs]
    for f in jobs:                       # anything the graph missed goes last
        if jobs[f] not in result.jobs:
            result.jobs.append(jobs[f])


def build_attr_jobs(root: CompNode, changes: Dict[str, Dict[str, str]]) -> JobPlan:
    """
    Jobs that only save Gusset tags (like a part's process) - no renaming.
    changes = {component key: {"process": "X-Carve"}}
    """
    result = JobPlan(active_file_name=root.file_name)
    nodes: Dict[str, CompNode] = {}
    file_names: Dict[str, str] = {}
    stack = [root]
    while stack:
        node = stack.pop()
        if node.key in nodes:
            continue
        nodes[node.key] = node
        if node.file_id:
            file_names[node.file_id] = node.file_name
        stack.extend(node.children)

    jobs: Dict[str, FileJob] = {}
    for key, attrs in changes.items():
        node = nodes.get(key)
        if node is None or not attrs:
            log.warning("Tag change for unknown component %s; skipped", key)
            continue
        is_file_root = bool(node.file_id) and (node.file_id == node.owner_file or node is root)
        edit = Edit(key=key, old_name=node.name, new_name=node.name, part_number=node.part_number,
                    description="", kind="", is_file_root=is_file_root, renumber=False, attrs=dict(attrs))
        if not node.owner_file:
            result.local_edits.append(edit)
        else:
            jobs.setdefault(node.owner_file, FileJob(node.owner_file, file_names.get(node.owner_file, ""))).edits.append(edit)

    _order_jobs(result, jobs, root, file_names)
    log.info("Tag jobs: %d local, %d linked file(s)", len(result.local_edits), len(result.jobs))
    return result


# ---------------------------------------------------------------------------
# Tag cache
# ---------------------------------------------------------------------------
# Fusion doesn't show an add-in's tags for parts linked TWO or more levels deep
# (a standoff linked into a gearbox that's linked into the chassis). Checked on a
# real minibot: the tags are saved in the standoff's file, but invisible from the
# chassis. So when Gusset tags a linked part's file, it also keeps a copy on the
# assemblies it saves anyway (and the open one), keyed by the part's file id.
TAG_CACHE_ATTR = "tag_cache"


def cache_entries(jobs: List[FileJob]) -> Dict[str, Dict[str, str]]:
    """{file id: tags} for every linked file whose ROOT got tags in these jobs."""
    cache: Dict[str, Dict[str, str]] = {}
    for job in jobs:
        for edit in job.edits:
            if not edit.is_file_root:
                continue
            entry = cache.setdefault(job.file_id, {})
            if edit.renumber:
                entry["pn"] = edit.part_number
                entry.setdefault("cots", "false")
                if edit.is_run_top:
                    entry["top"] = "true"
            if edit.cots_tag is not None:
                entry["cots"] = edit.cots_tag
            entry.update(edit.attrs)
    return {k: v for k, v in cache.items() if v}


def merge_cache(old: Dict[str, Dict[str, str]], new: Dict[str, Dict[str, str]],
                skip_file: str = "") -> Dict[str, Dict[str, str]]:
    merged = {k: dict(v) for k, v in old.items() if isinstance(v, dict)}
    for file_id, tags in new.items():
        if file_id == skip_file:
            continue
        merged.setdefault(file_id, {}).update(tags)
    return merged
