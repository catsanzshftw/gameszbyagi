#!/usr/bin/env python3
# MEGA BRICK BREAKOUT — Where BRICKS > ALL THE THINGS
# The bricks are alive, pulsing, exploding, and completely dominating the experience
# Window: 600x400 (2.5x upscale from 240x160 GBA base)

import math, random, time, sys, array
import pygame

# ----- Optional: numpy speeds up GBA color quantization (fallback if absent) -----
try:
    import numpy as np
    HAVE_NUMPY = True
except Exception:
    HAVE_NUMPY = False

# ---- Audio setup (Satellaview-ish beeps + AM noise ambience) ----
SAMPLE_RATE = 44100
pygame.mixer.pre_init(SAMPLE_RATE, size=-16, channels=2, buffer=512)
pygame.init()

# Window config: render to 240x160, upscale to 600x400 (exact 2.5x)
BASE_W, BASE_H = 240, 160
SCALE = 2.5
WIN_W, WIN_H = int(BASE_W * SCALE), int(BASE_H * SCALE)

# Gameplay tuning (base-resolution units per second)
PADDLE_W, PADDLE_H = 24, 3  # Smaller paddle - bricks dominate!
PADDLE_SPEED = 140.0
BALL_SPEED = 95.0  # slower base - bricks control the pace
BALL_R = 2
MAX_FPS_CAP = 240

# Visual style toggles
VIBES_ON = True
GBA_POSTFX_ON = True
BRICK_PARTICLES_ON = True

# ---- Small utility synth: create pygame.Sound from generated PCM bytes ----
def _sound_from_mono_i16(samples_i16):
    """samples_i16: array('h') mono; returns stereo pygame.Sound"""
    stereo = array.array('h')
    stereo.extend(s for pair in zip(samples_i16, samples_i16) for s in pair)
    return pygame.mixer.Sound(buffer=stereo.tobytes())

def tone(freq=880.0, dur=0.08, vol=0.35, shape="sine", sweep=0.0, vibrato=0.0, seed=None):
    n = int(SAMPLE_RATE * dur)
    buf = array.array('h')
    rng = random.Random(seed)
    phase = 0.0
    dt = 1.0 / SAMPLE_RATE
    for i in range(n):
        f = freq + sweep * (i / max(1, n - 1))
        if vibrato:
            f += vibrato * math.sin(2 * math.pi * 6.0 * (i * dt))
        phase += 2 * math.pi * f * dt
        s = math.sin(phase)
        if shape == "square":
            s = 1.0 if s >= 0 else -1.0
        elif shape == "triangle":
            s = 2.0 / math.pi * math.asin(math.sin(phase))
        elif shape == "noise":
            s = rng.uniform(-1.0, 1.0)
        s = max(-1.0, min(1.0, s))
        buf.append(int(s * vol * 32767))
    return _sound_from_mono_i16(buf)

def chirp(start=2200.0, end=900.0, dur=0.12, vol=0.3, shape="square"):
    sweep = end - start
    return tone(freq=start, dur=dur, vol=vol, shape=shape, sweep=sweep, vibrato=0.0)

def satellaview_ambience(dur=8.0, vol=0.08, seed=1337):
    n = int(SAMPLE_RATE * dur)
    buf = array.array('h')
    rng = random.Random(seed)
    dt = 1.0 / SAMPLE_RATE
    for i in range(n):
        t = i * dt
        am = 0.55 + 0.45 * math.sin(2 * math.pi * 0.35 * t)
        wob = math.sin(2 * math.pi * (120 + 5 * math.sin(2 * math.pi * 0.18 * t)) * t) * 0.15
        noise = (rng.random() * 2 - 1) * 0.85 * am
        s = (noise + wob) * vol
        buf.append(int(max(-1.0, min(1.0, s)) * 32767))
    return _sound_from_mono_i16(buf)

# Enhanced SFX for brick dominance
SFX = {
    "paddle": chirp(1400, 2000, 0.06, 0.28, "square"),
    "wall":   chirp(900,  700,  0.05, 0.22, "triangle"),
    "brick":  chirp(1900, 1200, 0.08, 0.33, "square"),
    "mega_brick": chirp(2400, 800, 0.15, 0.40, "square"),  # MEGA brick hit
    "pulse_brick": tone(440, 0.10, 0.25, "sine", sweep=220),  # Pulsing brick
    "explode": tone(150, 0.25, 0.35, "noise"),  # Brick explosion
    "lose":   tone(220, 0.35, 0.28, "triangle", sweep=-80),
    "win":    tone(880, 0.40, 0.30, "sine", sweep=60, vibrato=25),
    "serve":  tone(660, 0.18, 0.25, "square", sweep=120),
}
AMBIENCE = satellaview_ambience(dur=7.25, vol=0.08)
AMBIENCE_CHANNEL = None

# ---- Particle System for BRICK DOMINANCE ----
class Particle:
    def __init__(self, x, y, color, vx=0, vy=0, life=1.0, size=2):
        self.x, self.y = x, y
        self.vx, self.vy = vx, vy
        self.color = color
        self.life = life
        self.max_life = life
        self.size = size
        
    def update(self, dt):
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.vy += 120 * dt  # gravity
        self.life -= dt
        return self.life > 0
        
    def draw(self, surf):
        alpha = self.life / self.max_life
        size = int(self.size * alpha)
        if size > 0:
            # Clamp color values to valid range (0-255)
            col = tuple(max(0, min(255, int(c * alpha))) for c in self.color)
            pygame.draw.rect(surf, col, (int(self.x), int(self.y), size, size))

# ---- Colors / GBA-ish palette helpers ----
def rgb555_quantize_surf(surf):
    if not HAVE_NUMPY:
        return surf
    arr = pygame.surfarray.array3d(surf)
    arr = ((arr // 8) * 8).astype(arr.dtype)
    return pygame.surfarray.make_surface(arr)

def make_scanline_overlay(w, h, alpha=60):
    ov = pygame.Surface((w, h), pygame.SRCALPHA)
    dark = (0, 0, 0, alpha)
    for y in range(0, h, 2):
        pygame.draw.line(ov, dark, (0, y), (w, y))
    return ov

# ---- Game objects ----
class Paddle:
    def __init__(self, x, y):
        self.x, self.y = x, y
        self.w, self.h = PADDLE_W, PADDLE_H
        self.vx = 0.0

    @property
    def rect(self):
        return pygame.Rect(int(self.x), int(self.y), self.w, self.h)

class Ball:
    def __init__(self, x, y):
        self.x, self.y = x, y
        self.vx, self.vy = 0.0, 0.0
        self.r = BALL_R
        self.stuck = True
        self.trail = []  # Ball trail for visual effect

    @property
    def pos(self):
        return pygame.Vector2(self.x, self.y)

    @property
    def rect(self):
        return pygame.Rect(int(self.x - self.r), int(self.y - self.r), self.r * 2, self.r * 2)

# MEGA ENHANCED BRICK CLASS - BRICKS RULE!
class Brick:
    TYPES = ["normal", "mega", "pulsing", "moving", "explosive", "rainbow"]
    
    def __init__(self, x, y, w, h, hp, color, brick_type="normal"):
        self.rect = pygame.Rect(x, y, w, h)
        self.base_rect = self.rect.copy()
        self.hp = hp
        self.max_hp = hp
        self.color = color
        self.base_color = color
        self.type = brick_type
        self.pulse = 0.0
        self.move_phase = random.random() * math.pi * 2
        self.rainbow_phase = random.random() * math.pi * 2
        self.glow_intensity = 0.0
        
    def update(self, t, dt):
        # ALL BRICKS HAVE LIFE AND MOVEMENT
        if self.type == "pulsing" or self.type == "mega":
            self.pulse = math.sin(t * 3.0 + self.move_phase) * 0.5 + 0.5
            scale = 1.0 + self.pulse * 0.15
            cx, cy = self.base_rect.centerx, self.base_rect.centery
            w = int(self.base_rect.width * scale)
            h = int(self.base_rect.height * scale)
            self.rect = pygame.Rect(cx - w//2, cy - h//2, w, h)
            
        elif self.type == "moving":
            offset_x = math.sin(t * 2.0 + self.move_phase) * 8
            offset_y = math.cos(t * 1.5 + self.move_phase) * 3
            self.rect.x = self.base_rect.x + int(offset_x)
            self.rect.y = self.base_rect.y + int(offset_y)
            
        elif self.type == "explosive":
            # Subtle shake before explosion
            self.rect.x = self.base_rect.x + random.randint(-1, 1)
            self.rect.y = self.base_rect.y + random.randint(-1, 1)
            self.glow_intensity = math.sin(t * 8.0) * 0.5 + 0.5
            
        elif self.type == "rainbow":
            # Cycle through colors - ensure valid range
            hue = (t * 60 + self.rainbow_phase * 100) % 360
            r = max(0, min(255, int(127 + 127 * math.sin(math.radians(hue)))))
            g = max(0, min(255, int(127 + 127 * math.sin(math.radians(hue + 120)))))
            b = max(0, min(255, int(127 + 127 * math.sin(math.radians(hue + 240)))))
            self.color = (r, g, b)
            
        # All bricks get slight glow based on HP
        self.glow_intensity = min(1.0, self.hp / max(1, self.max_hp))

class Breakout:
    def __init__(self):
        self.window = pygame.display.set_mode((WIN_W, WIN_H))
        pygame.display.set_caption("MEGA BRICK BREAKOUT — BRICKS > EVERYTHING")
        self.base = pygame.Surface((BASE_W, BASE_H))
        self.scanlines = make_scanline_overlay(BASE_W, BASE_H, alpha=56)
        self.clock = pygame.time.Clock()
        self.font = pygame.font.Font(None, 12)
        self.big_font = pygame.font.Font(None, 20)
        self.small_font = pygame.font.Font(None, 10)
        self.particles = []
        self.screen_shake = 0.0
        self.reset(hard=True)

    def reset(self, hard=False):
        self.state = "title" if hard else "playing"
        self.score = 0 if hard else self.score
        self.lives = 3 if hard else self.lives
        self.level = 1 if hard else self.level
        self.particles = []
        self.screen_shake = 0.0

        # Field bounds
        self.bounds = pygame.Rect(8, 10, BASE_W - 16, BASE_H - 20)

        # Paddle & Ball
        px = self.bounds.centerx - PADDLE_W // 2
        py = self.bounds.bottom - 12
        self.paddle = Paddle(px, py)
        self.ball = Ball(px + PADDLE_W // 2, py - BALL_R - 1)
        self.ball.vx = 0.0
        self.ball.vy = 0.0
        self.ball.stuck = True

        # MEGA BRICK LAYOUT
        self.bricks = self.make_mega_level(self.level)
        self.combo = 0

        # Ambient audio
        global AMBIENCE_CHANNEL
        if VIBES_ON:
            if AMBIENCE_CHANNEL is None or not AMBIENCE_CHANNEL.get_busy():
                AMBIENCE_CHANNEL = AMBIENCE.play(loops=-1)
                if AMBIENCE_CHANNEL:
                    AMBIENCE_CHANNEL.set_volume(0.25)

    def next_level(self):
        self.level += 1
        self.lives += 1
        SFX["win"].play()
        # Celebration particles with valid colors!
        for _ in range(50):
            self.particles.append(Particle(
                BASE_W//2, BASE_H//2,
                (
                    max(0, min(255, random.randint(200, 255))),
                    max(0, min(255, random.randint(200, 255))),
                    max(0, min(255, random.randint(100, 255)))
                ),
                random.uniform(-100, 100), random.uniform(-150, -50),
                random.uniform(1.0, 2.0), random.randint(2, 4)
            ))
        self.reset(hard=False)

    def make_mega_level(self, level):
        """BRICKS ARE EVERYTHING - Bigger, fewer, more special"""
        rng = random.Random(level)
        rows = min(6, 3 + level // 2)  # Fewer but BIGGER
        cols = 8  # Fewer columns for BIGGER bricks
        bw, bh = 24, 12  # BIGGER BRICKS!
        total_w = cols * bw
        left = (BASE_W - total_w) // 2
        top = 20

        # Enhanced color palette
        palette = [
            (255, 100, 100), (100, 255, 100), (100, 100, 255),
            (255, 255, 100), (255, 100, 255), (100, 255, 255),
            (255, 180, 100), (180, 100, 255)
        ]
        
        bricks = []
        for r in range(rows):
            for c in range(cols):
                if rng.random() < 0.12:  # Some gaps for strategy
                    continue
                    
                x = left + c * bw
                y = top + r * bh
                
                # Determine brick type - MORE SPECIAL BRICKS!
                type_roll = rng.random()
                if type_roll < 0.15:
                    brick_type = "mega"
                    hp = 3 + level // 2
                    color = (255, 220, 100)  # Gold mega bricks
                elif type_roll < 0.30:
                    brick_type = "pulsing"
                    hp = 2
                    color = (220, 100, 255)  # Purple pulsing
                elif type_roll < 0.45:
                    brick_type = "moving"
                    hp = 2
                    color = (100, 220, 255)  # Cyan moving
                elif type_roll < 0.55:
                    brick_type = "explosive"
                    hp = 1
                    color = (255, 100, 100)  # Red explosive
                elif type_roll < 0.65:
                    brick_type = "rainbow"
                    hp = 2 + level // 3
                    color = palette[0]  # Will change
                else:
                    brick_type = "normal"
                    hp = 1 + r // 2
                    color = palette[(r + c + level) % len(palette)]
                
                bricks.append(Brick(x, y, bw - 1, bh - 1, hp, color, brick_type))
        
        return bricks

    def spawn_brick_particles(self, brick, hit_power=1.0):
        """BRICK EXPLOSION PARTICLES"""
        if not BRICK_PARTICLES_ON:
            return
            
        num_particles = int(10 * hit_power)
        cx, cy = brick.rect.centerx, brick.rect.centery
        
        for _ in range(num_particles):
            vx = random.uniform(-80, 80)
            vy = random.uniform(-120, -20)
            life = random.uniform(0.3, 0.8)
            size = random.randint(1, 3)
            # Particles match brick color with variation - CLAMP TO VALID RANGE
            r, g, b = brick.color
            r = max(0, min(255, r + random.randint(-30, 30)))
            g = max(0, min(255, g + random.randint(-30, 30)))
            b = max(0, min(255, b + random.randint(-30, 30)))
            self.particles.append(Particle(cx, cy, (r, g, b), vx, vy, life, size))

    def handle_input(self, dt):
        keys = pygame.key.get_pressed()
        ax = 0.0
        if keys[pygame.K_LEFT] or keys[pygame.K_a]:
            ax -= 1.0
        if keys[pygame.K_RIGHT] or keys[pygame.K_d]:
            ax += 1.0
        self.paddle.vx = ax * PADDLE_SPEED
        self.paddle.x += self.paddle.vx * dt
        
        if self.paddle.x < self.bounds.left:
            self.paddle.x = self.bounds.left
        if self.paddle.x + self.paddle.w > self.bounds.right:
            self.paddle.x = self.bounds.right - self.paddle.w

    def update_ball(self, dt):
        b = self.ball
        p = self.paddle

        # Update ball trail
        if not b.stuck and len(b.trail) < 8:
            b.trail.append((b.x, b.y))
        if len(b.trail) > 8:
            b.trail.pop(0)

        if b.stuck:
            b.x = p.x + p.w * 0.5
            b.y = p.y - b.r - 1
            b.trail = []
            return

        # Move
        b.x += b.vx * dt
        b.y += b.vy * dt

        # Walls
        if b.x - b.r <= self.bounds.left:
            b.x = self.bounds.left + b.r
            b.vx = abs(b.vx)
            SFX["wall"].play()
        if b.x + b.r >= self.bounds.right:
            b.x = self.bounds.right - b.r
            b.vx = -abs(b.vx)
            SFX["wall"].play()
        if b.y - b.r <= self.bounds.top:
            b.y = self.bounds.top + b.r
            b.vy = abs(b.vy)
            SFX["wall"].play()

        # Bottom (lose life)
        if b.y - b.r > self.bounds.bottom + 4:
            self.lives -= 1
            self.combo = 0
            SFX["lose"].play()
            b.trail = []
            if self.lives <= 0:
                self.state = "gameover"
                return
            b.stuck = True
            b.vx = b.vy = 0.0
            return

        # Paddle collision
        if b.rect.colliderect(p.rect):
            b.y = p.y - b.r - 1
            b.vy = -abs(b.vy)
            offset = (b.x - (p.x + p.w / 2)) / (p.w / 2)
            b.vx += (offset * 55.0) + (p.vx * 0.2)
            SFX["paddle"].play()

        # MEGA BRICK COLLISIONS
        hit_brick = None
        min_pen = 1e9
        hit_normal = pygame.Vector2(0, 0)
        ball_rect = b.rect
        
        for brick in self.bricks:
            if ball_rect.colliderect(brick.rect):
                r = brick.rect
                dx_left = (b.x + b.r) - r.left
                dx_right = r.right - (b.x - b.r)
                dy_top = (b.y + b.r) - r.top
                dy_bottom = r.bottom - (b.y - b.r)
                
                pen_x = min(dx_left, dx_right)
                pen_y = min(dy_top, dy_bottom)
                
                if pen_x < pen_y:
                    if dx_left < dx_right:
                        n = pygame.Vector2(-1, 0)
                    else:
                        n = pygame.Vector2(1, 0)
                    pen = pen_x
                else:
                    if dy_top < dy_bottom:
                        n = pygame.Vector2(0, -1)
                    else:
                        n = pygame.Vector2(0, 1)
                    pen = pen_y
                    
                if pen < min_pen:
                    min_pen = pen
                    hit_brick = brick
                    hit_normal = n

        if hit_brick:
            # Reflect velocity
            if hit_normal.x != 0:
                b.vx = -b.vx
                b.x += hit_normal.x * (min_pen + 0.5)
            if hit_normal.y != 0:
                b.vy = -b.vy
                b.y += hit_normal.y * (min_pen + 0.5)
            
            # BRICK IMPACT!
            hit_brick.hp -= 1
            
            # Screen shake for impact
            if hit_brick.type == "mega" or hit_brick.type == "explosive":
                self.screen_shake = 0.3
                SFX["mega_brick"].play()
            elif hit_brick.type == "pulsing":
                SFX["pulse_brick"].play()
            else:
                SFX["brick"].play()
            
            # Spawn particles
            self.spawn_brick_particles(hit_brick, 1.0 if hit_brick.hp <= 0 else 0.5)
            
            # Track bricks to remove (avoid modifying list during iteration)
            bricks_to_remove = []
            
            # Handle special brick destruction effects
            if hit_brick.hp <= 0:
                bricks_to_remove.append(hit_brick)
                
                if hit_brick.type == "explosive":
                    # EXPLOSION! Damage nearby bricks
                    SFX["explode"].play()
                    self.screen_shake = 0.5
                    self.spawn_brick_particles(hit_brick, 3.0)
                    cx, cy = hit_brick.rect.centerx, hit_brick.rect.centery
                    
                    for other in self.bricks:
                        if other != hit_brick and other not in bricks_to_remove:
                            ox, oy = other.rect.centerx, other.rect.centery
                            dist = math.hypot(cx - ox, cy - oy)
                            if dist < 40:  # Explosion radius
                                other.hp -= 1
                                self.spawn_brick_particles(other, 0.3)
                                if other.hp <= 0:
                                    bricks_to_remove.append(other)
                                    self.score += 25
                
                self.score += 100 + 20 * self.combo
                if hit_brick.type == "mega":
                    self.score += 150  # Bonus for mega bricks
            else:
                self.score += 50
            
            # Remove all destroyed bricks
            for brick in bricks_to_remove:
                if brick in self.bricks:
                    self.bricks.remove(brick)
                
            self.combo = min(self.combo + 1, 15)
            
            # Speed up slightly
            speed = math.hypot(b.vx, b.vy)
            speed = min(speed * 1.02, 200.0)
            ang = math.atan2(b.vy, b.vx)
            b.vx, b.vy = math.cos(ang) * speed, math.sin(ang) * speed

            if not self.bricks:
                self.next_level()

    def update_particles(self, dt):
        self.particles = [p for p in self.particles if p.update(dt)]
        
    def update_screen_shake(self, dt):
        self.screen_shake = max(0, self.screen_shake - dt * 2)

    def draw_vibe_background(self, t):
        # BRICK-THEMED animated gradient
        for y in range(self.base.get_height()):
            u = y / self.base.get_height()
            # Brick-inspired colors - clamped to valid range
            r = max(0, min(255, int(48 + 32 * (1 + math.sin(t * 1.7 + u * 6.0)))))
            g = max(0, min(255, int(24 + 24 * (1 + math.sin(t * 1.3 + u * 5.2 + 2.0)))))
            b = max(0, min(255, int(32 + 28 * (1 + math.sin(t * 0.9 + u * 4.0 + 4.0)))))
            self.base.fill((r, g, b), pygame.Rect(0, y, BASE_W, 1))

    def draw_static_background(self):
        self.base.fill((16, 20, 28))

    def draw_world(self, dt, fps):
        t = pygame.time.get_ticks() * 0.001
        
        # Update systems
        self.update_particles(dt)
        self.update_screen_shake(dt)
        
        # Background
        if VIBES_ON:
            self.draw_vibe_background(t)
        else:
            self.draw_static_background()

        # Screen shake offset
        shake_x = random.uniform(-self.screen_shake * 3, self.screen_shake * 3)
        shake_y = random.uniform(-self.screen_shake * 3, self.screen_shake * 3)
        
        # Bounds
        bounds_rect = self.bounds.move(int(shake_x), int(shake_y))
        pygame.draw.rect(self.base, (12, 12, 16), bounds_rect, 2)

        # Update and draw MEGA BRICKS
        for br in self.bricks:
            br.update(t, dt)
            
            # Draw brick with glow effect
            if br.glow_intensity > 0:
                glow_rect = br.rect.inflate(4, 4)
                glow_color = tuple(max(0, min(255, int(c * 0.3 * br.glow_intensity))) for c in br.color)
                pygame.draw.rect(self.base, glow_color, glow_rect)
            
            # Main brick
            pygame.draw.rect(self.base, br.color, br.rect)
            
            # Highlight for multi-HP bricks
            if br.hp > 1:
                highlight = tuple(max(0, min(255, c + 50)) for c in br.color)
                pygame.draw.rect(self.base, highlight, br.rect.inflate(-2, -2), 1)
            
            # Border
            pygame.draw.rect(self.base, (0, 0, 0), br.rect, 1)

        # Draw particles
        for p in self.particles:
            p.draw(self.base)

        # Ball trail effect
        for i, (tx, ty) in enumerate(self.ball.trail):
            alpha = i / max(1, len(self.ball.trail))
            size = int(self.ball.r * alpha)
            if size > 0:
                col = (
                    max(0, min(255, int(255 * alpha))),
                    max(0, min(255, int(240 * alpha))),
                    max(0, min(255, int(192 * alpha)))
                )
                pygame.draw.circle(self.base, col, (int(tx), int(ty)), size)

        # Paddle (smaller, less important)
        pygame.draw.rect(self.base, (200, 200, 200), self.paddle.rect)

        # Ball
        pygame.draw.circle(self.base, (255, 240, 192), (int(self.ball.x), int(self.ball.y)), self.ball.r)

        # HUD
        hud = f"BRICKS: {len(self.bricks):02d}  SCORE {self.score:06d}  LV {self.level}  FPS {fps:3.0f}"
        self.base.blit(self.small_font.render(hud, True, (248, 248, 248)), (8, 2))

        # Title / overlays
        if self.state == "title":
            msg = "BRICKS > ALL THE THINGS"
            sub = "SPACE: serve • ←/→ move • V: vibes • G: GBA • B: particles"
            self.base.blit(self.big_font.render(msg, True, (255, 255, 210)), (25, 54))
            self.base.blit(self.small_font.render(sub, True, (225, 225, 210)), (18, 80))
            
            # Demo brick animation on title
            demo_y = 100 + int(math.sin(t * 2) * 5)
            demo_color = (
                max(0, min(255, int(127 + 127 * math.sin(t * 3)))),
                max(0, min(255, int(127 + 127 * math.sin(t * 3 + 2)))),
                max(0, min(255, int(127 + 127 * math.sin(t * 3 + 4))))
            )
            pygame.draw.rect(self.base, demo_color, (BASE_W//2 - 20, demo_y, 40, 15))
            pygame.draw.rect(self.base, (0, 0, 0), (BASE_W//2 - 20, demo_y, 40, 15), 1)
            
        elif self.state == "gameover":
            msg = "BRICKS WIN"
            sub = "Press R to restart"
            self.base.blit(self.big_font.render(msg, True, (255, 180, 180)), (72, 56))
            self.base.blit(self.small_font.render(sub, True, (240, 220, 220)), (82, 80))

        # GBA postFX
        post = self.base
        if GBA_POSTFX_ON:
            post = rgb555_quantize_surf(post)
            post.blit(self.scanlines, (0, 0), special_flags=pygame.BLEND_RGBA_SUB)

        # Upscale to window
        scaled = pygame.transform.scale(post, (WIN_W, WIN_H))
        self.window.blit(scaled, (0, 0))
        pygame.display.flip()

    def run(self):
        global VIBES_ON, GBA_POSTFX_ON, AMBIENCE_CHANNEL, BRICK_PARTICLES_ON
        running = True
        fps_cap = MAX_FPS_CAP

        while running:
            dt = self.clock.tick(fps_cap) / 1000.0
            fps = self.clock.get_fps()

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False
                    elif event.key == pygame.K_v:
                        VIBES_ON = not VIBES_ON
                        if not VIBES_ON and AMBIENCE_CHANNEL:
                            AMBIENCE_CHANNEL.stop()
                            AMBIENCE_CHANNEL = None
                        elif VIBES_ON and (AMBIENCE_CHANNEL is None or not AMBIENCE_CHANNEL.get_busy()):
                            AMBIENCE_CHANNEL = AMBIENCE.play(loops=-1)
                            if AMBIENCE_CHANNEL: AMBIENCE_CHANNEL.set_volume(0.25)
                    elif event.key == pygame.K_g:
                        GBA_POSTFX_ON = not GBA_POSTFX_ON
                    elif event.key == pygame.K_b:
                        BRICK_PARTICLES_ON = not BRICK_PARTICLES_ON
                    elif event.key == pygame.K_m:
                        if AMBIENCE_CHANNEL and AMBIENCE_CHANNEL.get_busy():
                            AMBIENCE_CHANNEL.stop()
                            AMBIENCE_CHANNEL = None
                        else:
                            AMBIENCE_CHANNEL = AMBIENCE.play(loops=-1)
                            if AMBIENCE_CHANNEL: AMBIENCE_CHANNEL.set_volume(0.25)
                    elif event.key == pygame.K_f:
                        fps_cap = 60 if self.clock.get_fps() > 61 else MAX_FPS_CAP
                    elif event.key == pygame.K_r:
                        self.score, self.lives, self.level = 0, 3, 1
                        self.reset(hard=True)
                    elif event.key == pygame.K_SPACE:
                        if self.state == "title":
                            self.state = "playing"
                            SFX["serve"].play()
                        elif self.state == "gameover":
                            self.score, self.lives, self.level = 0, 3, 1
                            self.reset(hard=True)
                        elif self.ball.stuck:
                            ang = math.radians(random.uniform(40, 140))
                            speed = BALL_SPEED
                            self.ball.vx = speed * math.cos(ang)
                            self.ball.vy = -abs(speed * math.sin(ang))
                            self.ball.stuck = False
                            SFX["serve"].play()

            if self.state in ("title", "gameover"):
                self.handle_input(dt)
                self.draw_world(dt, fps)
                continue

            # Playing
            self.handle_input(dt)
            self.update_ball(dt)
            self.draw_world(dt, fps)

        pygame.quit()

# ---- Entry point ----
if __name__ == "__main__":
    Breakout().run()
