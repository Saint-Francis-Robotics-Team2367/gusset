"""
config.py - add-in level constants (NOT team settings; those live in
gusset_config.json and are edited with the Settings button).
"""

import os

VERSION = "0.13.2"

# Updates: the public GitHub repo ("owner/name") that holds release/latest.json and
# team_settings.json. Leave "OWNER/gusset" until the repo exists - updates stay off.
UPDATE_REPO = "Saint-Francis-Robotics-Team2367/gusset"
UPDATE_BRANCH = "main"

# True = detailed DEBUG lines in Text Commands and logs/gusset.log.
# Set to False for releases you publish to other teams.
DEBUG = True

ADDIN_DIR = os.path.dirname(os.path.abspath(__file__))

TAB_ID = "GussetTab"
TAB_NAME = "GUSSET"

PANEL_NAMING_ID = "Gusset_NamingPanel"
PANEL_NAMING_NAME = "Naming"

PANEL_BOM_ID = "Gusset_BomPanel"
PANEL_BOM_NAME = "BOM"

PANEL_FAB_ID = "Gusset_FabPanel"
PANEL_FAB_NAME = "Fab"

PANEL_FEATURES_ID = "Gusset_FeaturesPanel"
PANEL_FEATURES_NAME = "Features"

PANEL_PARTS_ID = "Gusset_PartsPanel"
PANEL_PARTS_NAME = "Parts"

PANEL_COTS_ID = "Gusset_CotsPanel"
PANEL_COTS_NAME = "COTS"

PANEL_REVIEW_ID = "Gusset_ReviewPanel"
PANEL_REVIEW_NAME = "Review"
