"""Regenerates the toolbar icons in resources/. Run: python tools/make_icons.py"""
import os
from PIL import Image, ImageDraw

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "resources")
S = 256  # draw big, shrink down for crisp edges

def tag(d, c):
    d.polygon([(40,70),(150,70),(220,128),(150,186),(40,186)], outline=c, width=18)
    d.ellipse((70,112,102,144), fill=c)
    d.line((120,110,175,110), fill=c, width=12); d.line((120,146,160,146), fill=c, width=12)

def check(d, c):
    d.rounded_rectangle((50,40,206,226), radius=18, outline=c, width=16)
    d.rectangle((95,26,161,58), fill=c)
    d.line((85,135,118,170), fill=c, width=20); d.line((118,170,178,100), fill=c, width=20)

def gear(d, c):
    import math
    for i in range(8):
        a = i*math.pi/4
        x, y = 128+88*math.cos(a), 128+88*math.sin(a)
        d.ellipse((x-22,y-22,x+22,y+22), fill=c)
    d.ellipse((50,50,206,206), fill=c)
    d.ellipse((96,96,160,160), fill=(0,0,0,0))

def sheet(d, c):
    d.rounded_rectangle((44,30,212,226), radius=16, outline=c, width=16)
    for y in (80,124,168):
        d.line((76,y,180,y), fill=c, width=12)
    d.line((112,62,112,196), fill=c, width=10)

def face(d, c):
    d.polygon([(40,90),(150,40),(216,90),(106,140)], outline=c, width=14)
    d.line((40,90,40,170), fill=c, width=14); d.line((106,140,106,220), fill=c, width=14); d.line((216,90,216,170), fill=c, width=14)
    d.line((40,170,106,220), fill=c, width=14); d.line((106,220,216,170), fill=c, width=14)

def stack(d, c):
    for i, y in enumerate((60, 110, 160)):
        d.rounded_rectangle((40 + i*14, y, 200 + i*14, y + 40), radius=8, outline=c, width=12)
    d.polygon([(206,20),(236,50),(206,80)], fill=c)

def holes(d, c):
    d.rounded_rectangle((28,92,228,164), radius=10, outline=c, width=12)
    for x in (68,108,148,188):
        d.ellipse((x-12,116,x+12,140), fill=c)

def bearing(d, c):
    import math
    d.ellipse((36,36,220,220), outline=c, width=14)
    d.ellipse((92,92,164,164), outline=c, width=14)
    for i in range(8):
        a = i*math.pi/4; x, y = 128+64*math.cos(a), 128+64*math.sin(a)
        d.ellipse((x-12,y-12,x+12,y+12), fill=c)

def review(d, c):
    d.rounded_rectangle((52,30,204,226), radius=14, outline=c, width=14)
    for y in (80,128,176):
        d.rectangle((76,y-10,96,y+10), outline=c, width=6)
        d.line((112,y,184,y), fill=c, width=10)

def part3d(d, c):
    d.polygon([(128,30),(216,78),(216,178),(128,226),(40,178),(40,78)], outline=c, width=14)
    d.line((40,78,128,126), fill=c, width=12); d.line((216,78,128,126), fill=c, width=12); d.line((128,126,128,226), fill=c, width=12)

def truss(d, c):
    d.rounded_rectangle((24,64,232,192), radius=12, outline=c, width=12)
    for a, b in (((40,180),(92,76)), ((92,76),(144,180)), ((144,180),(196,76)), ((196,76),(220,170)), ((40,180),(144,180)), ((92,76),(196,76))):
        d.line((a, b), fill=c, width=10)

def pockets(d, c):
    d.rounded_rectangle((24,52,232,204), radius=14, fill=c)
    for poly in (((48,78),(118,78),(48,178)), ((138,78),(208,78),(208,178)), ((60,180),(128,96),(196,180))):
        d.polygon(poly, fill=(0,0,0,0))

def tube(d, c):
    d.polygon(((40,96),(176,40),(232,72),(96,128)), outline=c, width=12)
    d.line(((40,96),(40,176)), fill=c, width=12); d.line(((96,128),(96,208)), fill=c, width=12)
    d.line(((232,72),(232,152)), fill=c, width=12); d.line(((40,176),(96,208)), fill=c, width=12)
    d.line(((96,208),(232,152)), fill=c, width=12)
    d.rectangle((52,116,84,176), outline=c, width=8)

def hexshaft(d, c):
    import math as m
    pts = [(128 + 96*m.cos(m.pi/3*k + m.pi/6), 128 + 96*m.sin(m.pi/3*k + m.pi/6)) for k in range(6)]
    d.polygon(pts, outline=c, width=16)
    pts2 = [(128 + 44*m.cos(m.pi/3*k + m.pi/6), 128 + 44*m.sin(m.pi/3*k + m.pi/6)) for k in range(6)]
    d.polygon(pts2, fill=c)

def belt(d, c):
    d.ellipse((24,88,104,168), outline=c, width=12); d.ellipse((136,48,232,144+64-64), outline=c, width=12)
    d.line(((60,88),(176,48)), fill=c, width=12); d.line(((60,168),(190,142)), fill=c, width=12)
    d.ellipse((56,120,72,136), fill=c); d.ellipse((176,88,192,104), fill=c)

def box(d, c):
    # a parts box (COTS library)
    d.polygon(((128,30),(226,78),(128,126),(30,78)), outline=c, width=14)
    d.line(((30,78),(30,182)), fill=c, width=14); d.line(((226,78),(226,182)), fill=c, width=14)
    d.line(((128,126),(128,232)), fill=c, width=14)
    d.line(((30,182),(128,232)), fill=c, width=14); d.line(((128,232),(226,182)), fill=c, width=14)

def box_add(d, c):
    box(d, c)
    d.ellipse((150,150,250,250), fill=c)
    d.line(((200,170),(200,230)), fill=(0,0,0,0), width=16); d.line(((170,200),(230,200)), fill=(0,0,0,0), width=16)

for name, draw in (("cots", box), ("cots_add", box_add), ("tube", tube), ("shaft", hexshaft), ("belt", belt), ("quick_rib", truss), ("lighten", pockets), ("export_part", part3d), ("hole_pattern", holes), ("bearing_pocket", bearing), ("design_review", review), ("name_parts", tag), ("check_names", check), ("settings", gear), ("export_bom", sheet),
                   ("export_face", face), ("fab_export", stack)):
    folder = os.path.join(ROOT, name); os.makedirs(folder, exist_ok=True)
    for suffix, color in (("", (60,60,60,255)), ("-dark", (225,225,225,255))):
        img = Image.new("RGBA", (S,S), (0,0,0,0)); draw(ImageDraw.Draw(img), color)
        for size in (16, 32, 64):
            img.resize((size,size), Image.LANCZOS).save(os.path.join(folder, f"{size}x{size}{suffix}.png"))
    print("icons ->", folder)
