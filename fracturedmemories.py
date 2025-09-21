import pygame, sys, random
from collections import deque  # (NEW) for simple breadcrumb trails

pygame.init()
pygame.mixer.init()

SCREEN_W, SCREEN_H = 750, 400
TILE = 16
FPS = 480

screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
pygame.display.set_caption("Fractured Memories")

# Custom icon (kept)
try:
    icon = pygame.image.load("icon.png").convert_alpha()
    pygame.display.set_icon(icon)
except Exception:
    pass

clock = pygame.time.Clock()

# ------- Assets -------
tileset = pygame.image.load("tileset.png").convert_alpha()
frisk_sheet = pygame.image.load("frisk.png").convert_alpha()
sans_sprite = pygame.image.load("sans.png").convert_alpha()
papyrus_sprite = pygame.image.load("papyrus.png").convert_alpha()
toriel_sprite = pygame.image.load("toriel.png").convert_alpha()
fight_sprite = pygame.image.load("fight.png").convert_alpha()
act_sprite = pygame.image.load("act.png").convert_alpha()
item_sprite = pygame.image.load("item.png").convert_alpha()
mercy_sprite = pygame.image.load("mercy.png").convert_alpha()
flowey_sprite = pygame.image.load("flowey.png").convert_alpha()
snowdrake_sprite = pygame.image.load("snowdrake.png").convert_alpha()
snowdin_tileset = pygame.image.load("snowdin_tileset.png").convert_alpha()
font = pygame.font.Font("font.ttf", 12)

# ---- Optional background layers (VISUAL-ONLY) ----
# Safe if missing; we just skip.
bg_ruins = None
bg_snowdin = None
try:
    bg_ruins = pygame.image.load("bg_ruins.png").convert()
except Exception:
    bg_ruins = None
try:
    bg_snowdin = pygame.image.load("bg_snowdin.png").convert()
except Exception:
    bg_snowdin = None

# Battle sprites – SOUL + bullet images
soul_img_raw = pygame.image.load("icon.png").convert_alpha()
soul_img = pygame.transform.smoothscale(soul_img_raw, (12, 12))  # scaled properly
bullet_img_raw = pygame.image.load("bullet.png").convert_alpha()
bullet_img = pygame.transform.smoothscale(bullet_img_raw, (8, 8))

# Keep consistent music extension everywhere to avoid load errors
pygame.mixer.music.load("intro_theme.mp3")
pygame.mixer.music.set_volume(0.5)
pygame.mixer.music.play(-1)

W, H = 40, 30

def make_map(with_fragments=False, area="ruins"):
    layout = [[(0, 0) for _ in range(W)] for _ in range(H)]
    for x in range(W):
        layout[0][x] = layout[H-1][x] = (1.5, 0)  # Walls
    for y in range(H):
        layout[y][0] = layout[y][W-1] = (1.5, 0)  # Walls
    if with_fragments and area == "ruins":
        for fx, fy in [(5,5), (10,8), (15,12)]:
            layout[fy][fx] = (2, 0)  # Memory fragments
    # Doors
    layout[15][1] = (3, 0)
    layout[15][38] = (3, 0)
    return layout, area

rooms = {
    "ruins_start": make_map(with_fragments=True, area="ruins")[0],
    "ruins_toriel": make_map(area="ruins")[0],
    "ruins_flowey": make_map(area="ruins")[0],
    "snowdin_start": make_map(area="snowdin")[0],
    # extra Snowdin rooms
    "snowdin_path": make_map(area="snowdin")[0],
    "snowdin_clearing": make_map(area="snowdin")[0],
    "snowdin_cavern": make_map(area="snowdin")[0],
}

tilesets = {
    "ruins": tileset,
    "snowdin": snowdin_tileset
}

current_room = "ruins_start"
current_area = "ruins"

door_exit = (38, 15)
door_entry = (1, 15)

# ---- Door & Room Graph ----
ROOM_AREA = {
    "ruins_start": "ruins",
    "ruins_toriel": "ruins",
    "ruins_flowey": "ruins",
    "snowdin_start": "snowdin",
    "snowdin_path": "snowdin",
    "snowdin_clearing": "snowdin",
    "snowdin_cavern": "snowdin",
}

ROOM_GRAPH = {
    # Ruins chain
    "ruins_start":   {"forward": "ruins_toriel",   "back": None},
    "ruins_toriel":  {"forward": "ruins_flowey",   "back": "ruins_start"},
    "ruins_flowey":  {"forward": "snowdin_start",  "back": "ruins_toriel"},  # requires Flowey defeated

    # Snowdin chain
    "snowdin_start":   {"forward": "snowdin_path",     "back": None},           # no back to Ruins by design
    "snowdin_path":    {"forward": "snowdin_clearing", "back": "snowdin_start"},
    "snowdin_clearing":{"forward": "snowdin_cavern",   "back": "snowdin_path"},
    "snowdin_cavern":  {"forward": None,               "back": "snowdin_clearing"},
}

fragment_positions = [(5,5), (10,8), (15,12)]
memory_fragments = 0
total_fragments = len(fragment_positions)

def get_tile(tx, ty, area):
    surf = pygame.Surface((TILE, TILE), pygame.SRCALPHA)
    surf.blit(tilesets[area], (0, 0), (tx*TILE, ty*TILE, TILE, TILE))
    return surf

def is_walkable(x, y, layout):
    return 0 <= x < W and 0 <= y < H and layout[y][x] in [(0,0), (2,0), (3,0)]

# ---------- VISUAL HELPERS (NEW, draw-only) ----------
def make_vignette(size):
    w, h = size
    vg = pygame.Surface((w, h), pygame.SRCALPHA)
    # radial alpha falloff
    cx, cy = w/2, h/2
    max_d2 = (cx*cx + cy*cy)
    arr = pygame.PixelArray(vg)
    for y in range(h):
        dy = (y - cy)
        dy2 = dy*dy
        for x in range(w):
            dx = (x - cx)
            a = int(180 * ((dx*dx + dy2) / max_d2))  # 0 center -> 180 edges
            if a > 200: a = 200
            arr[x, y] = (0 << 24) | (0 << 16) | (0 << 8) | a
    del arr
    return vg

VIGNETTE = make_vignette((SCREEN_W, SCREEN_H))

def area_tint_surface(area):
    tint = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
    if area == "ruins":
        tint.fill((40, 0, 40, 25))   # faint purple shadow
    elif area == "snowdin":
        tint.fill((0, 40, 60, 30))   # cold teal wash
    else:
        tint.fill((0, 0, 0, 0))
    return tint

# ---------- Particles (NEW, visual only) ----------
class Particle:
    __slots__ = ("x","y","vx","vy","life","max_life","kind")
    def __init__(self, x, y, vx, vy, life, kind):
        self.x, self.y = x, y
        self.vx, self.vy = vx, vy
        self.life = life
        self.max_life = life
        self.kind = kind

    def update(self):
        self.x += self.vx
        self.y += self.vy
        self.life -= 1
        return self.life <= 0

    def draw(self, surf, ox=0, oy=0):
        a = max(0, min(255, int(255 * (self.life / max(1, self.max_life)))))
        if self.kind == "snow":
            pygame.draw.rect(surf, (255,255,255), pygame.Rect(int(self.x)-ox, int(self.y)-oy, 2, 2))
        elif self.kind == "puff":
            pygame.draw.circle(surf, (220, 220, 220), (int(self.x)-ox, int(self.y)-oy), 2)
        elif self.kind == "spark":
            pygame.draw.rect(surf, (255, 255, 120), pygame.Rect(int(self.x)-ox, int(self.y)-oy, 2, 2))

class ParticleSystem:
    def __init__(self):
        self.items = []

    def add(self, p: Particle):
        self.items.append(p)

    def update(self):
        for p in self.items[:]:
            if p.update():
                self.items.remove(p)

    def draw(self, surf, ox=0, oy=0):
        for p in self.items:
            p.draw(surf, ox, oy)

particles = ParticleSystem()

def spawn_footstep_puff(px, py):
    # tiny dust puff at world pixel coords
    for _ in range(2):
        vx = random.uniform(-0.2, 0.2)
        vy = random.uniform(-0.1, -0.3)
        particles.add(Particle(px, py+TILE/2, vx, vy, life=18, kind="puff"))

def ensure_snowfall():
    # keep ~120 flakes on screen in Snowdin
    on_screen = [p for p in particles.items if p.kind == "snow"
                 and 0 <= p.x <= SCREEN_W and 0 <= p.y <= SCREEN_H]
    lack = 120 - len(on_screen)
    for _ in range(max(0, lack)):
        x = random.uniform(0, SCREEN_W)
        y = random.uniform(-20, SCREEN_H)
        vx = random.uniform(-0.2, 0.2)
        vy = random.uniform(0.4, 0.9)
        p = Particle(x, y, vx, vy, life=random.randint(160, 320), kind="snow")
        particles.add(p)

def fragment_sparkles(ox, oy, layout):
    # sparkle around any tile == (2,0)
    for (fx, fy) in fragment_positions:
        if 0 <= fy < H and 0 <= fx < W and layout[fy][fx] == (2,0):
            if random.random() < 0.2:
                # world pixel coords for center of tile
                cx = fx * TILE + TILE/2
                cy = fy * TILE + TILE/2
                for _ in range(2):
                    vx = random.uniform(-0.15, 0.15)
                    vy = random.uniform(-0.15, -0.25)
                    particles.add(Particle(cx, cy, vx, vy, life=20, kind="spark"))

# ---------- CLASSES ----------
class DialogueBox:
    def __init__(self, font):
        self.font = font
        self.lines = []
        self.index = 0
        self.visible = False
        self.surf = pygame.Surface((500,70))
        self.rect = self.surf.get_rect(midbottom=(SCREEN_W//2, SCREEN_H-10))
    def show(self, lines):
        self.lines = lines
        self.index = 0
        self.visible = True
    def next(self):
        self.index += 1
        if self.index >= len(self.lines):
            self.visible = False
    def draw(self, surf):
        if not self.visible:
            return
        self.surf.fill((0,0,0))
        pygame.draw.rect(self.surf, (216,0,255), self.surf.get_rect(), 2)
        text = self.font.render(self.lines[self.index], True, (255,255,255))
        self.surf.blit(text,(10,20))
        surf.blit(self.surf, self.rect)

class Player:
    def __init__(self, x, y):
        self.tx = x
        self.ty = y
        self.px = x * TILE
        self.py = y * TILE
        self.tx_target = self.px
        self.ty_target = self.py
        self.moving = False
        self.speed = 1

        self.frames = []
        fw, fh = 17, 29
        for i in range(4):
            f = pygame.Surface((fw, fh), pygame.SRCALPHA)
            f.blit(frisk_sheet, (0, 0), (i*fw, 0, fw, fh))
            self.frames.append(f)
        self.cur = 0
        self.timer = 0
        self.delay = 15
        self.hp = 20
        self.slip_dx = 0
        self.slip_dy = 0

        # (VISUAL) remember last tile to spawn puffs when step begins
        self._last_step_tile = (x, y)

    def handle(self, keys, layout):
        if self.moving:
            return
        dx = dy = 0
        if keys[pygame.K_LEFT]: dx = -1
        elif keys[pygame.K_RIGHT]: dx = 1
        elif keys[pygame.K_UP]: dy = -1
        elif keys[pygame.K_DOWN]: dy = 1
        nx, ny = self.tx + dx, self.ty + dy
        if (dx or dy) and is_walkable(nx, ny, layout):
            self.tx, self.ty = nx, ny
            self.tx_target, self.ty_target = nx*TILE, ny*TILE
            self.moving = True
            # breadcrumb for followers
            trails['frisk'].append((self.tx, self.ty))
            # footstep puff (spawn at start of tile move)
            world_px = self.tx * TILE
            world_py = self.ty * TILE
            spawn_footstep_puff(world_px, world_py)
            self._last_step_tile = (self.tx, self.ty)

            if current_area == "snowdin" and (self.slip_dx != 0 or self.slip_dy != 0):
                nx, ny = self.tx + self.slip_dx, self.ty + self.slip_dy
                if is_walkable(nx, ny, layout):
                    self.tx, self.ty = nx, ny
                    self.tx_target, self.ty_target = nx * TILE, ny * TILE
                    self.moving = True
                    trails['frisk'].append((self.tx, self.ty))
                else:
                    self.slip_dx = 0
                    self.slip_dy = 0
                return

    def update(self):
        if self.moving:
            if self.px < self.tx_target:
                self.px += self.speed
            elif self.px > self.tx_target:
                self.px -= self.speed
            if self.py < self.ty_target:
                self.py += self.speed
            elif self.py > self.ty_target:
                self.py -= self.speed
            if abs(self.px - self.tx_target) <= self.speed and abs(self.py - self.ty_target) <= self.speed:
                self.px, self.py = self.tx_target, self.ty_target
                self.moving = False
        if self.moving:
            self.timer += 1
            if self.timer >= self.delay:
                self.timer = 0
                self.cur = (self.cur + 1) % len(self.frames)
        else:
            self.cur = 0
    def draw(self, surf, ox, oy):
        surf.blit(self.frames[self.cur], (self.px-ox, self.py-oy))

class NPC:
    def __init__(self, x,y, sprite, lines, battle=False, enemy_id=None):
        self.tx, self.ty = x,y
        self.sprite = sprite
        self.lines = lines
        self.talked = False
        self.battle = battle
        self.enemy_id = enemy_id  # which enemy this NPC triggers
        self.defeated = False
        self.post_battle_dialogue_shown = False
    def draw(self, surf, ox, oy):
        if not self.defeated:
            surf.blit(self.sprite, (self.tx*TILE-ox, self.ty*TILE-oy))

class Bullet:
    def __init__(self, rect, vx, vy):
        self.rect = rect
        self.vx = vx
        self.vy = vy

# ======= Followers =======
class Follower:
    """
    Simple chain follower:
      - Reads leader's breadcrumb queue with a small lag so it trails behind.
      - Papyrus follows Sans; Sans follows Frisk.
    """
    def __init__(self, name, sprite, leader_name, start_tx, start_ty, lag_steps=2, speed=1):
        self.name = name
        self.sprite = sprite
        self.leader_name = leader_name
        self.tx = start_tx
        self.ty = start_ty
        self.px = start_tx * TILE
        self.py = start_ty * TILE
        self.tx_target = self.px
        self.ty_target = self.py
        self.moving = False
        self.speed = speed
        self.lag = lag_steps

    def update(self, layout):
        # If not moving, see if leader has enough breadcrumbs to take a step
        src = trails.get(self.leader_name)
        if not self.moving and src is not None and len(src) > self.lag:
            target = src.popleft()  # consume one breadcrumb after lag
            nx, ny = target
            if is_walkable(nx, ny, layout):
                self.tx, self.ty = nx, ny
                self.tx_target, self.ty_target = nx * TILE, ny * TILE
                self.moving = True
                # publish our own breadcrumb for whoever follows us
                trails.setdefault(self.name, deque()).append((nx, ny))

        # Pixel-by-pixel slide
        if self.moving:
            if self.px < self.tx_target:
                self.px += self.speed
            elif self.px > self.tx_target:
                self.px -= self.speed
            if self.py < self.ty_target:
                self.py += self.speed
            elif self.py > self.ty_target:
                self.py -= self.speed
            if abs(self.px - self.tx_target) <= self.speed and abs(self.py - self.ty_target) <= self.speed:
                self.px, self.py = self.tx_target, self.ty_target
                self.moving = False

    def draw(self, surf, ox, oy):
        surf.blit(self.sprite, (self.px - ox, self.py - oy))

# follower state
trails = {'frisk': deque(), 'sans': deque()}
active_followers = []

def teleport_followers_to_player():
    """Keep the chain in sync on room changes / acceptance."""
    for f in active_followers:
        f.tx = player.tx
        f.ty = player.ty
        f.px = player.tx * TILE
        f.py = player.ty * TILE
        f.tx_target = f.px
        f.ty_target = f.py
        f.moving = False
    trails['frisk'].clear()
    trails['sans'].clear()

def start_allies_following():
    """Called when you accept Sans & Papyrus as allies."""
    # remove Snowdin Sans NPC if present
    if snowdin_sans_npc in npcs.get("snowdin_start", []):
        npcs["snowdin_start"].remove(snowdin_sans_npc)
    # spawn followers at player's tile
    teleport_followers_to_player()
    active_followers.clear()
    s = Follower("sans", sans_sprite, leader_name="frisk",
                 start_tx=player.tx, start_ty=player.ty, lag_steps=2, speed=1)
    p = Follower("papyrus", papyrus_sprite, leader_name="sans",
                 start_tx=player.tx, start_ty=player.ty, lag_steps=2, speed=1)
    active_followers.extend([s, p])

def change_room(next_room, via="forward"):
    """Centralized room swap to avoid subtle mistakes."""
    global current_room, current_area, layout, asked_allies, choosing_allies, ally_choice_index
    current_room = next_room
    current_area = ROOM_AREA[next_room]
    layout, _ = make_map(area=current_area)

    if via == "forward":
        player.tx, player.ty = door_entry  # you appear just inside the new room
    else:
        player.tx, player.ty = door_exit   # coming back places you at the far door

    player.px, player.py = player.tx * TILE, player.ty * TILE
    teleport_followers_to_player()

    # Trigger ally choice the FIRST time we reach Snowdin
    if next_room == "snowdin_start" and not asked_allies:
        asked_allies = True
        dialogue.show([
            "* Sans: Hey, kid... listen.",
            "* Things are getting weird.",
            "* Papyrus and I can tag along, if you want.",
            "* We'll watch your back."
        ])
        choosing_allies = True
        ally_choice_index = 0

# ------- Enemy Database -------
ENEMIES = {
    "Flowey": {
        "max_hp": 50,
        "dialogues": {
            1: ["Flowey: Hehehe...", "Let's see how you handle this!"],
            2: ["Flowey: Not bad...", "But I’m just getting started!"],
            3: ["Flowey: You really think you can win?", "This is hopeless!"],
            4: ["Flowey: No... No... NO!", "This can't be!"],
            5: ["Flowey: How... how did you survive?!"]
        },
        "post": [
            "* Flowey: ...Stop...",
            "* Flowey: Please... just... stop...",
            "* Flowey: I... I can't... I can't control it...",
            "* Flowey: It's... not me... I'm still here... Asriel...",
            "* Flowey: But... I can't fight it... not anymore...",
            "* Flowey: Go... go and find the truth... ",
            "* Flowey: before it's too late...",
            "* Flowey: ...Thank you..."
        ],
        "music": "battle_theme.mp3",
        "type": "flowey"
    },
    "Ice Jester": {
        "max_hp": 45,
        "dialogues": {
            1: ["* Ice Jester: Tada! Try to dodge a punchline!", "* The air gets colder."],
            2: ["* Ice Jester: Laugh it off!", "* Shards start zig-zagging."],
            3: ["* Ice Jester: The final gag...", "* The wind howls."]
        },
        "post": ["* Ice Jester: ...okay, that one’s on me.", "* The cold eases slightly."],
        "music": "battle_theme.mp3",
        "type": "ice_jester"
    },
    "Snowdrake Echo": {
        "max_hp": 55,
        "dialogues": {
            1: ["* Echo: heh... heh... heh...", "* Your moves echo back at you."],
            2: ["* Echo: can you keep up with yourself?", "* Reflections fly in arcs."],
            3: ["* Echo: ...quiet... too quiet...", "* The echoes distort."]
        },
        "post": ["* The echoes fade.", "* Snowdrake Echo slumps, calm."],
        "music": "battle_theme.mp3",
        "type": "echo"
    },
    "Shard Beast": {
        "max_hp": 70,
        "dialogues": {
            1: ["* The Shard Beast snarls.", "* Black crystals rattle."],
            2: ["* Corruption surges!", "* Heavy shards slam the box."],
            3: ["* It thrashes wildly.", "* The corruption recoils."]
        },
        "post": ["* The corruption flakes away.", "* You saved a monster from the Shard."],
        "music": "battle_theme.mp3",
        "type": "shard_minion"
    }
}

# ------- Ally Battle Flavor -------
ALLY_BANTER = [
    "* Sans: i'll chip in... when it counts.",
    "* Papyrus: NYEH HEH HEH! OBSERVE MY ASSIST!",
    "* Sans: remember, kid—left, right, left.",
    "* Papyrus: DO NOT FEAR! THE GREAT PAPYRUS SHALL PROTECT YOU!",
]
ALLY_ATTACK_LINES = {
    "sans": [
        "* Sans snaps his fingers. A quick hit lands!",
        "* Sans: whoops. slipped.",
    ],
    "papyrus": [
        "* Papyrus lunges with flair!",
        "* Papyrus: BEHOLD! MY FOCUSED STRIKE!",
    ]
}

# ------- Battle state -------
in_battle = False
player_turn = False
enemy_turn_timer = 0
enemy_turn_duration = 180  # kept

battle_box = pygame.Rect(30, 140, 260, 60)
soul_rect = pygame.Rect(150, 151, 12, 12)  # match soul_img size
soul_speed = 0.6
bullets = []
bullet_timer = -1
bullet_interval = 100
hit_cooldown = 0

# "Flowey" vars are now used for the CURRENT ENEMY (kept names to minimize churn)
flowey_hp = 50
pending_enemy_turn = False
flowey_phase = 1
selected_option = 0
current_enemy_id = "Flowey"   # switches per battle
current_enemy_npc = None      # set when battle starts

def enemy_dialogue_for_phase(eid, phase):
    d = ENEMIES[eid]["dialogues"]
    keys = sorted(d.keys())
    key = keys[min(phase-1, len(keys)-1)]
    return d[key]

def spawn_bullets(phase):
    bullets.clear()
    etype = ENEMIES[current_enemy_id]["type"]

    # FLOWEY patterns (original kept — bullet visuals already images; we’ll revise patterns later if you want)
    if etype == "flowey":
        if phase == 1:
            for _ in range(4):
                x = random.randint(battle_box.left + 12, battle_box.right - 12)
                rect = pygame.Rect(x, battle_box.top, 8, 8)
                bullets.append(Bullet(rect, 0, 3))
        elif phase == 2:
            for _ in range(4):
                x = random.randint(battle_box.left + 12, battle_box.right - 12)
                rect = pygame.Rect(x, battle_box.top, 8, 8)
                bullets.append(Bullet(rect, 0, 3))
        elif phase == 3:
            for _ in range(4):
                y = random.randint(battle_box.top + 12, battle_box.bottom - 12)
                side = random.choice(["left", "right"])
                if side == "left":
                    rect = pygame.Rect(battle_box.left, y, 8, 8)
                    bullets.append(Bullet(rect, 4, 0))
                else:
                    rect = pygame.Rect(battle_box.right - 8, y, 8, 8)
                    bullets.append(Bullet(rect, -4, 0))
            for _ in range(3):
                x = random.randint(battle_box.left + 12, battle_box.right - 12)
                rect = pygame.Rect(x, battle_box.top, 8, 8)
                bullets.append(Bullet(rect, 0, 4))
        elif phase == 4:
            for _ in range(6):
                side = random.choice(["top-left", "top-right"])
                if side == "top-left":
                    rect = pygame.Rect(battle_box.left, battle_box.top, 8, 8)
                    bullets.append(Bullet(rect, 3, 3))
                else:
                    rect = pygame.Rect(battle_box.right - 8, battle_box.top, 8, 8)
                    bullets.append(Bullet(rect, -3, 3))
        elif phase >= 5:
            for _ in range(4):
                y = random.randint(battle_box.top + 12, battle_box.bottom - 12)
                side = random.choice(["left", "right"])
                if side == "left":
                    rect = pygame.Rect(battle_box.left, y, 8, 8)
                    bullets.append(Bullet(rect, 4, 0))
                else:
                    rect = pygame.Rect(battle_box.right - 8, battle_box.top, 8, 8)
                    bullets.append(Bullet(rect, -3, 3))

    # ICE JESTER patterns (zig-zag + diagonal chill)
    elif etype == "ice_jester":
        for _ in range(3 + phase):
            x = random.randint(battle_box.left + 12, battle_box.right - 12)
            vx = random.choice([-2, 2, -3, 3])
            rect = pygame.Rect(x, battle_box.top, 8, 8)
            bullets.append(Bullet(rect, vx, 3))
        if phase >= 2:
            for _ in range(2):
                side = random.choice(["tl", "tr"])
                if side == "tl":
                    rect = pygame.Rect(battle_box.left, battle_box.top, 8, 8)
                    bullets.append(Bullet(rect, 2, 2))
                else:
                    rect = pygame.Rect(battle_box.right - 8, battle_box.top, 8, 8)
                    bullets.append(Bullet(rect, -2, 2))

    # ECHO patterns (arcing reflections)
    elif etype == "echo":
        for _ in range(2 + phase):
            y = random.randint(battle_box.top + 10, battle_box.bottom - 10)
            side = random.choice(["left", "right"])
            if side == "left":
                rect = pygame.Rect(battle_box.left, y, 8, 8)
                bullets.append(Bullet(rect, 3, random.choice([-2, -1, 1, 2])))
            else:
                rect = pygame.Rect(battle_box.right - 8, y, 8, 8)
                bullets.append(Bullet(rect, -3, random.choice([-2, -1, 1, 2])))
        if phase >= 3:
            # small rain
            for _ in range(3):
                x = random.randint(battle_box.left + 12, battle_box.right - 12)
                rect = pygame.Rect(x, battle_box.top, 8, 8)
                bullets.append(Bullet(rect, 0, 4))

    # SHARD MINION patterns (heavy shards + side slams)
    elif etype == "shard_minion":
        for _ in range(2 + phase):
            x = random.randint(battle_box.left + 14, battle_box.right - 14)
            rect = pygame.Rect(x, battle_box.top, 8, 8)
            bullets.append(Bullet(rect, 0, 4))
        # side slams
        for _ in range(2 if phase < 3 else 4):
            y = random.randint(battle_box.top + 10, battle_box.bottom - 10)
            side = random.choice(["left", "right"])
            if side == "left":
                rect = pygame.Rect(battle_box.left, y, 8, 8)
                bullets.append(Bullet(rect, 5, 0))
            else:
                rect = pygame.Rect(battle_box.right - 8, y, 8, 8)
                bullets.append(Bullet(rect, -5, 0))

def reset_battle():
    global in_battle, player_turn, flowey_hp, flowey_phase, selected_option, bullets, current_enemy_npc
    in_battle = False
    player_turn = True
    flowey_hp = ENEMIES[current_enemy_id]["max_hp"]
    flowey_phase = 1
    selected_option = 0
    bullets.clear()
    player.hp = 20
    current_enemy_npc = None

def draw_battle():
    screen.fill((0,0,0))

    # (VISUAL) subtle parallax grid backdrop inside the battle box
    pygame.draw.rect(screen, (0,255,0), battle_box, 2)
    bg = pygame.Surface(battle_box.size)
    bg.fill((10,10,10))
    # light grid lines
    for x in range(0, battle_box.w, 8):
        pygame.draw.line(bg, (18,18,18), (x,0), (x,battle_box.h), 1)
    for y in range(0, battle_box.h, 8):
        pygame.draw.line(bg, (18,18,18), (0,y), (battle_box.w,y), 1)
    screen.blit(bg, battle_box.topleft)

    # Soul sprite
    screen.blit(soul_img, soul_rect.topleft)

    # bullets as images
    for bullet in bullets:
        screen.blit(bullet_img, bullet.rect.topleft)

    # menu
    menu_sprites = [fight_sprite, act_sprite, item_sprite, mercy_sprite]

    for i, sprite in enumerate(menu_sprites):
        x = 32 + i * 75
        y = 210
        # Draw selection box
        rect = pygame.Rect(x, y, sprite.get_width(), sprite.get_height())
        color = (255, 255, 255) if i == selected_option else (255, 132, 40)
        pygame.draw.rect(screen, color, rect.inflate(4, 4), 2)
        # Blit sprite
        screen.blit(sprite, rect.topleft)

    # (VISUAL) HP bars
    # player
    screen.blit(font.render(f"HP", True, (255,255,255)), (10, 10))
    hp_bar = pygame.Rect(34, 12, 80, 8)
    pygame.draw.rect(screen, (80,80,80), hp_bar)
    if player.hp > 0:
        w = int(hp_bar.w * (player.hp / 20))
        pygame.draw.rect(screen, (255, 200, 60), (hp_bar.x, hp_bar.y, w, hp_bar.h))
    pygame.draw.rect(screen, (255,255,255), hp_bar, 1)

    # enemy
    name_text = font.render(f"{current_enemy_id}", True, (255,255,255))
    screen.blit(name_text, (10, 26))
    e_bar = pygame.Rect(10, 40, 140, 6)
    pygame.draw.rect(screen, (80,80,80), e_bar)
    if flowey_hp > 0:
        ew = int(e_bar.w * (flowey_hp / ENEMIES[current_enemy_id]["max_hp"]))
        pygame.draw.rect(screen, (255, 90, 90), (e_bar.x, e_bar.y, ew, e_bar.h))
    pygame.draw.rect(screen, (255,255,255), e_bar, 1)

    # dialogue line (fallback if no dialogue visible)
    if dialogue.visible:
        dialogue.draw(screen)
    else:
        line = enemy_dialogue_for_phase(current_enemy_id, flowey_phase)[0]
        screen.blit(font.render(line, True, (255,255,255)), (10, 54))

def ally_try_attack():
    """Allies sometimes attack before enemy turn starts."""
    global flowey_hp, pending_enemy_turn
    did_any = False
    lines = []

    if active_followers:
        # Not too often: ~30% Sans, ~25% Papyrus each turn
        if any(f.name == "sans" for f in active_followers) and random.random() < 0.30:
            dmg = random.randint(3, 7)
            flowey_hp = max(0, flowey_hp - dmg)
            lines.append(random.choice(ALLY_ATTACK_LINES["sans"]) + f" (-{dmg})")
            did_any = True
        if any(f.name == "papyrus" for f in active_followers) and random.random() < 0.25:
            dmg = random.randint(4, 8)
            flowey_hp = max(0, flowey_hp - dmg)
            lines.append(random.choice(ALLY_ATTACK_LINES["papyrus"]) + f" (-{dmg})")
            did_any = True

        # Rare banter (~15%)
        if random.random() < 0.15:
            lines.append(random.choice(ALLY_BANTER))

    if did_any:
        dialogue.show(lines)
        pending_enemy_turn = True
        return True
    return False

def update_enemy_turn():
    global flowey_phase, bullet_timer, hit_cooldown, player_turn, flowey_hp, in_battle, pending_enemy_turn

    # Always decrement cooldown
    if hit_cooldown > 0:
        hit_cooldown -= 1

    bullet_timer += 1
    if bullet_timer >= bullet_interval:
        bullet_timer = 0
        spawn_bullets(flowey_phase)

    for bullet in bullets[:]:
        bullet.rect.x += bullet.vx
        bullet.rect.y += bullet.vy

        if not battle_box.colliderect(bullet.rect):
            bullets.remove(bullet)
            continue

        # Slightly tighter collision to avoid “standing still hits”
        if bullet.rect.colliderect(soul_rect.inflate(-1, -1)) and hit_cooldown == 0:
            damage = random.randint(2, 5)
            player.hp -= damage
            hit_cooldown = 60  # 1 second cooldown-ish
            bullets.clear()
            dialogue.show([f"* You took {damage} damage!"])
            return False  # pause updates while dialogue shows

    if player.hp <= 0:
        dialogue.show(["* You have been defeated..."])
        reset_battle()
        pygame.mixer.music.load("intro_theme.mp3")
        pygame.mixer.music.play(-1)
        return True  # Battle ends

    # Phase progression
    max_phase = 5 if ENEMIES[current_enemy_id]["type"] == "flowey" else 3
    if flowey_hp <= 0:
        flowey_phase += 1
        if flowey_phase > max_phase:
            # mark defeated NPC, show post lines
            if current_enemy_npc:
                current_enemy_npc.defeated = True
            dialogue.show(ENEMIES[current_enemy_id]["post"])
            if current_enemy_npc:
                current_enemy_npc.post_battle_dialogue_shown = True
            in_battle = False
            pending_enemy_turn = False
            pygame.mixer.music.load("intro_theme.mp3")
            pygame.mixer.music.play(-1)
            return True
        else:
            flowey_hp = ENEMIES[current_enemy_id]["max_hp"]
            bullets.clear()
            dialogue.show(enemy_dialogue_for_phase(current_enemy_id, flowey_phase))
            player_turn = True
            return False

    # End enemy turn when safe
    if hit_cooldown == 0 and not dialogue.visible:
        player_turn = True

    return False

# ===================== INITIALISATION =====================
dialogue = DialogueBox(font)
player = Player(2,2)

# NPCs
npcs = {
    "ruins_start": [
        NPC(8,10, sans_sprite, ["* Sans: Something feels off...", "* Sans: Be careful."]),
        NPC(12,15, papyrus_sprite, ["* Papyrus: I WILL RESTORE ORDER!", "NYEH!"])
    ],
    "ruins_toriel": [
        NPC(20,15, toriel_sprite, ["* Toriel: ...Who... are you?", "* Toriel: This place... it feels wrong... so wrong..."])
    ],
    "ruins_flowey": [
        NPC(20,15, flowey_sprite, ["* Flowey: Hehehe...", "You won't last long..."], battle=True, enemy_id="Flowey")
    ],
    "snowdin_start": [
        NPC(15,10, sans_sprite, ["* Sans: Hey, you made it to Snowdin. Not bad.",
                                 "* Sans: This place is... different, isn’t it? Feels kinda off.",
                                 "* Sans: Keep your wits about you. Things aren’t always what they seem.",
                                 "* Sans: Oh, and one more thing... don’t forget to look around. You might find something useful.",
                                 "* Sans: Good luck out there. You’re gonna need it."])
    ],
    # Snowdin expanded rooms with enemies
    "snowdin_path": [
        NPC(20,12, toriel_sprite, ["* Footprints... and scratch marks. The forest watches."]),

        NPC(34, 15, flowey_sprite, ["* A trickster emerges from the flurries..."], battle=True, enemy_id="Ice Jester")
    ],
    "snowdin_clearing": [
        NPC(18,14, snowdrake_sprite, ["* An echo answers your steps..."], battle=True, enemy_id="Snowdrake Echo")
    ],
    "snowdin_cavern": [
        NPC(22,15, flowey_sprite, ["* The corruption crawls..."], battle=True, enemy_id="Shard Beast")
    ],
}
flowey_npc = npcs["ruins_flowey"][0]
snowdin_sans_npc = npcs["snowdin_start"][0] if npcs["snowdin_start"] else None

# -------- Ally-choice state --------
asked_allies = False
choosing_allies = False
ally_choice_index = 0
have_sans = False
have_papyrus = False

# ===================== PROLOGUE CUTSCENE (kept) =====================
cutscene = True
dialogue.show([
    "* After the barrier was broken, monsters and humans lived together peacefully...",
    "* Frisk, having saved everyone, finally felt at peace.",
    "* One afternoon on the surface, everyone gathered for a picnic.",
    "* Suddenly, Frisk's vision blurred... A voice whispered:",
    "* 'One perfect timeline... No more resets... No more pain...'",
    "* A crushing headache overwhelmed them...",
    "* Darkness.",
    "* ..."
])

layout, current_area = make_map(with_fragments=True, area="ruins")

# ===================== MAIN LOOP =====================
running = True
while running:
    keys = pygame.key.get_pressed()
    for e in pygame.event.get():
        if e.type == pygame.QUIT:
            running = False

        elif e.type == pygame.KEYDOWN:
            # If the dialogue box is up, Z advances
            if dialogue.visible:
                if e.key == pygame.K_z:
                    dialogue.next()
                    if not dialogue.visible and pending_enemy_turn:
                        pending_enemy_turn = False
                        player_turn = False
                        enemy_turn_timer = 0
                        spawn_bullets(flowey_phase)
                    if not dialogue.visible and cutscene:
                        cutscene = False
                    # post-battle cleanup already handled generically

            # Ally choice input when no dialogue is showing
            elif choosing_allies and not dialogue.visible:
                if e.key == pygame.K_LEFT:
                    ally_choice_index = (ally_choice_index - 1) % 2
                elif e.key == pygame.K_RIGHT:
                    ally_choice_index = (ally_choice_index + 1) % 2
                elif e.key == pygame.K_z:
                    if ally_choice_index == 0:
                        have_sans = True
                        have_papyrus = True
                        dialogue.show(["* Sans and Papyrus have joined you!"])
                        choosing_allies = False
                        start_allies_following()   # start the chain & hide Snowdin Sans
                    else:
                        dialogue.show(["* You decide to go on alone..."])
                        choosing_allies = False

            # Normal input
            elif not in_battle:
                if e.key == pygame.K_z:
                    px, py = player.tx, player.ty
                    for npc in npcs.get(current_room, []):
                        if npc.defeated:
                            continue
                        if abs(px - npc.tx) <= 1 and abs(py - npc.ty) <= 1:
                            # Flowey special gating: if already defeated and finished post, skip
                            if npc is flowey_npc and flowey_npc.defeated and flowey_npc.post_battle_dialogue_shown:
                                continue

                            # Start dialogue / battle
                            npc.talked = True
                            if npc.battle and not in_battle:
                                current_enemy_id = npc.enemy_id or "Flowey"
                                current_enemy_npc = npc
                                pygame.mixer.music.load(ENEMIES[current_enemy_id]["music"])
                                pygame.mixer.music.play(-1)
                                in_battle = True
                                player_turn = False
                                flowey_phase = 1
                                flowey_hp = ENEMIES[current_enemy_id]["max_hp"]
                                dialogue.show(enemy_dialogue_for_phase(current_enemy_id, flowey_phase))
                                soul_rect.size = (12, 12)  # keep rect in sync with image
                                soul_rect.center = battle_box.center
                            else:
                                dialogue.show(npc.lines)
                            break

            elif in_battle and not dialogue.visible:
                if player_turn:
                    if e.key == pygame.K_LEFT:
                        selected_option = (selected_option - 1) % 4
                    elif e.key == pygame.K_RIGHT:
                        selected_option = (selected_option + 1) % 4
                    elif e.key == pygame.K_z:
                        if selected_option == 0:  # FIGHT
                            damage = random.randint(5, 10)
                            flowey_hp = max(0, flowey_hp - damage)
                            dialogue.show([f"* You attacked for {damage} damage!"])
                            # After player's attack, allies might also chip in
                            pending_enemy_turn = True
                            if not dialogue.visible:
                                if ally_try_attack():
                                    pass
                        elif selected_option == 1:  # ACT
                            dialogue.show(["* You tried to be friendly... it eyes you warily."])
                            pending_enemy_turn = True
                            if not dialogue.visible:
                                ally_try_attack()
                        elif selected_option == 2:  # ITEM
                            dialogue.show(["* You have no items."])
                            pending_enemy_turn = True
                            if not dialogue.visible:
                                ally_try_attack()
                        elif selected_option == 3:  # MERCY
                            # generic mercy rule: spare if phase is last and hp <= 10
                            max_phase = 5 if ENEMIES[current_enemy_id]["type"] == "flowey" else 3
                            if flowey_phase == max_phase and flowey_hp <= 10:
                                dialogue.show(["* You spared the foe."])
                                # treat as victory
                                flowey_phase += 1
                                pending_enemy_turn = False
                            else:
                                dialogue.show(["* It's not ready to be spared."])
                                pending_enemy_turn = True
                                if not dialogue.visible:
                                    ally_try_attack()

                        if not dialogue.visible and pending_enemy_turn:
                            # Start enemy turn unless there's a dialogue queued
                            player_turn = False
                            spawn_bullets(flowey_phase)

    # ---------------- Battle input & update ----------------
    if in_battle and not dialogue.visible:
        if not player_turn:
            keys = pygame.key.get_pressed()
        if keys[pygame.K_LEFT] and soul_rect.left > battle_box.left:
            soul_rect.x -= soul_speed
        if keys[pygame.K_RIGHT] and soul_rect.right < battle_box.right:
            soul_rect.x += soul_speed
        if keys[pygame.K_UP] and soul_rect.top > battle_box.top:
            soul_rect.y -= soul_speed
        if keys[pygame.K_DOWN] and soul_rect.bottom < battle_box.bottom:
            soul_rect.y += soul_speed

        if update_enemy_turn():  # Battle may end
            pass

        draw_battle()
        pygame.display.flip()
        continue

    # ---------------- Exploration ----------------
    if not dialogue.visible and not cutscene and not in_battle:
        player.handle(keys, layout)
    player.update()

    # update followers during exploration
    if active_followers and not in_battle:
        for f in active_followers:
            f.update(layout)

    px, py = player.tx, player.ty

    # Memory fragment pickup
    if current_area == "ruins" and (px, py) in fragment_positions and layout[py][px] == (2,0):
        layout[py][px] = (0,0)
        memory_fragments += 1
        dialogue.show([f"* Memory restored! {memory_fragments}/{total_fragments}"])

    # ---------------- Door transitions ----------------
    if not in_battle and not dialogue.visible and not cutscene:
        # Forward transitions (right-side door)
        if (px, py) == door_exit:
            nxt = ROOM_GRAPH[current_room]["forward"]

            # Gate Ruins -> Snowdin on Flowey defeat
            if current_room == "ruins_flowey" and not flowey_npc.defeated:
                nxt = None

            if nxt:
                change_room(nxt, via="forward")

        # Back transitions (left-side door)
        elif (px, py) == door_entry:
            prv = ROOM_GRAPH[current_room]["back"]
            if prv:
                change_room(prv, via="back")

    # ---------------- Draw world ----------------
    screen.fill((0,0,0))
    ox, oy = player.px - SCREEN_W//2 + TILE//2, player.py - SCREEN_H//2 + TILE//2

    # (VISUAL) Parallax background per area (if images present)
    if current_area == "ruins" and bg_ruins:
        # slow parallax (move at ~20% camera speed)
        bx = int(ox * 0.2) % bg_ruins.get_width()
        by = int(oy * 0.2) % bg_ruins.get_height()
        for ix in range(-1, 2):
            for iy in range(-1, 2):
                screen.blit(bg_ruins, (-(bx) + ix*bg_ruins.get_width(), -(by) + iy*bg_ruins.get_height()))
    elif current_area == "snowdin" and bg_snowdin:
        bx = int(ox * 0.2) % bg_snowdin.get_width()
        by = int(oy * 0.2) % bg_snowdin.get_height()
        for ix in range(-1, 2):
            for iy in range(-1, 2):
                screen.blit(bg_snowdin, (-(bx) + ix*bg_snowdin.get_width(), -(by) + iy*bg_snowdin.get_height()))

    # Tilemap
    for y in range(H):
        for x in range(W):
            tx, ty = layout[y][x]
            screen.blit(get_tile(tx, ty, current_area), (x*TILE - ox, y*TILE - oy))

    # NPCs
    for npc in npcs.get(current_room, []):
        npc.draw(screen, ox, oy)

    # followers (behind player so player stays readable)
    if active_followers and not in_battle:
        for f in active_followers:
            f.draw(screen, ox, oy)

    # player
    player.draw(screen, ox, oy)

    # (VISUAL) fragment sparkles
    fragment_sparkles(ox, oy, layout)

    # (VISUAL) area-specific particles
    if current_area == "snowdin":
        ensure_snowfall()

    # update/draw particles over world
    particles.update()
    particles.draw(screen, ox, oy)

    # HUD: fragments
    frag_text = font.render(f"Memory Fragments: {memory_fragments}/{total_fragments}", True, (255,255,255))
    screen.blit(frag_text, (5,5))

    # Dialogue
    dialogue.draw(screen)

    # Ally choice overlay – drawn when active and no dialogue
    if choosing_allies and not dialogue.visible:
        prompt = font.render("Let Sans & Papyrus join?", True, (255,255,255))
        screen.blit(prompt, (SCREEN_W//2 - prompt.get_width()//2, 90))
        opts = ["Yes", "No"]
        for i, o in enumerate(opts):
            rect = pygame.Rect(80+i*140, 120, 100, 24)
            color = (255,255,255) if i == ally_choice_index else (180, 100, 0)
            pygame.draw.rect(screen, color, rect, 2)
            label = font.render(o, True, (255,255,255))
            screen.blit(label, (rect.x + (rect.w - label.get_width())//2, rect.y+4))

    # (VISUAL) area tint + vignette last
    screen.blit(area_tint_surface(current_area), (0,0))
    screen.blit(VIGNETTE, (0,0))

    pygame.display.flip()
    # (kept) your framerate rule exactly
    clock.tick(360 if FPS < 360 else FPS)

pygame.quit()
sys.exit()
