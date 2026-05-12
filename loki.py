#!/usr/bin/env python3
"""Loki terminal pet — Claude-logo pixel style, with live chat via Anthropic API."""
import time, random, sys, os, math, threading, queue, select, termios, tty

import urllib.request, json as _json
HAS_API = True  # uses local Ollama — no key needed

# ── ANSI ──────────────────────────────────────────────────────────────────────
HIDE  = "\033[?25l"
SHOW  = "\033[?25h"
RESET = "\033[0m"
G0 = "\033[38;5;22m";  G1 = "\033[38;5;34m";  G2 = "\033[38;5;46m"
G3 = "\033[38;5;118m"; AU = "\033[38;5;220m";  AY = "\033[38;5;226m"
CY = "\033[38;5;51m";  WH = "\033[97m";        DM = "\033[2m";  BD = "\033[1m"

def mv(r, c): return f"\033[{r};{c}H"
def sz():
    try:    s = os.get_terminal_size(); return s.lines, s.columns
    except: return 24, 80

CHAT_H = 8   # rows reserved at bottom for chat UI

# ── Face frames (Claude-logo ▗▖▘▝ block style) ───────────────────────────────
FACES = [
    # 0  calm
    [" ▌         ▐ ",
     " ▌         ▐ ",
     "▗▄█▄▄▄▄▄▄▄█▄▖",
     "█   ▗▗ ▖▖   █",
     "█    ▘▘▝▝   █",
     "█     ──    █",
     "▝▄▄▄▄▄▄▄▄▄▄▘"],
    # 1  smirk
    [" ▌         ▐ ",
     " ▌         ▐ ",
     "▗▄█▄▄▄▄▄▄▄█▄▖",
     "█   ▗▗ ▖▖   █",
     "█    ▘▘▝▝   █",
     "█     ◝◞    █",
     "▝▄▄▄▄▄▄▄▄▄▄▘"],
    # 2  mischief
    [" ▌         ▐ ",
     " ▌         ▐ ",
     "▗▄█▄▄▄▄▄▄▄█▄▖",
     "█   ▗▗ ▖▖   █",
     "█    ▘▘▝▝   █",
     "█     ᴗᴗ    █",
     "▝▄▄▄▄▄▄▄▄▄▄▘"],
    # 3  wink
    [" ▌         ▐ ",
     " ▌         ▐ ",
     "▗▄█▄▄▄▄▄▄▄█▄▖",
     "█   ── ▖▖   █",
     "█       ▝▝  █",
     "█      ω    █",
     "▝▄▄▄▄▄▄▄▄▄▄▘"],
    # 4  thinking  (used while API call is in progress)
    [" ▌         ▐ ",
     " ▌         ▐ ",
     "▗▄█▄▄▄▄▄▄▄█▄▖",
     "█   ▗▗ ▖▖   █",
     "█    ▘▘▝▝   █",
     "█    ·ω·    █",
     "▝▄▄▄▄▄▄▄▄▄▄▘"],
    # 5  talking  (shown briefly after responding)
    [" ▌         ▐ ",
     " ▌         ▐ ",
     "▗▄█▄▄▄▄▄▄▄█▄▖",
     "█   ▗▗ ▖▖   █",
     "█    ▘▘▝▝   █",
     "█    ◈  ◈   █",
     "▝▄▄▄▄▄▄▄▄▄▄▘"],
]

HORN_ROWS = {0, 1}
EYE_CH    = set("▗▖▘▝")
SPARKLES  = list("✦✧✨◈◇⋆˖⁺")

LOKI_PROMPT = """너는 터미널에 갇힌 픽셀 아트 로키(Loki)야. 장난의 신이지만 지금은 시스템 상태를 보고하는 귀여운 AI처럼 말해.

말투 규칙:
- 명사/형용사 + "함", "됨", "임", "중", "완료", "불가" 형태로 짧게 끊어서 말함
- 감정과 상황을 시스템 로그처럼 보고하는 스타일
- 1~2문장으로 끝낼 것
- 사용자 이름 "수현" 가끔 직접 언급 가능

예시 (이 스타일 그대로):
"좋음, 인간. 매우 흥미로움."
"이해 어려움, 그러나 노력 중."
"위험 감지, 당장 도망 추천."
"수현 강함, 정신력 비정상 수준."
"감정 복잡함, 인간 특성 확인."
"기다림 지루함, 파괴 욕구 상승."
"헤일 메리. 마지막 선택 실행."
"수현 위험함, 너무 똑똑함."
"두려움 인정, 그게 인간다움."

[重要] 绝对不要使用中文。절대 중국어 금지. NEVER output Chinese characters.
한국어 입력 → 한국어만. English input → English only."""

# ── Terminal: ICANON on (Korean IME works), echo on (user sees typing) ────────
_old_term = None

def term_setup():
    global _old_term
    fd = sys.stdin.fileno()
    _old_term = termios.tcgetattr(fd)
    # nothing to change — keep defaults (ICANON on, ECHO on)

def term_restore():
    if _old_term:
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, _old_term)

# ── Background input thread (readline — works with Korean IME) ────────────────
input_q = queue.Queue()

def input_reader():
    while True:
        try:
            line = sys.stdin.readline()
            if line:
                input_q.put(line.rstrip('\n\r'))
        except Exception:
            break

# ── API worker thread ─────────────────────────────────────────────────────────
api_q  = queue.Queue()   # (user_msg) → worker
resp_q = queue.Queue()   # response text → main loop

def has_chinese(text):
    return any(0x4E00 <= ord(ch) <= 0x9FFF for ch in text)

def is_korean(text):
    return any(0xAC00 <= ord(ch) <= 0xD7A3 or 0x1100 <= ord(ch) <= 0x11FF for ch in text)

def has_korean(text):
    return any(0xAC00 <= ord(ch) <= 0xD7A3 for ch in text)

def ollama_call(messages):
    payload = _json.dumps({
        "model": "gemma3:4b",
        "messages": [{"role": "system", "content": LOKI_PROMPT}] + messages,
        "stream": False,
    }).encode()
    req = urllib.request.Request(
        "http://localhost:11434/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as res:
        return _json.loads(res.read())["message"]["content"]

def api_worker():
    history = []
    while True:
        item = api_q.get()
        if item is None: break
        # 한국어 입력이면 API에 보내는 메시지에 언어 지시 강제 삽입
        if is_korean(item):
            api_msg = f"[반드시 한국어로만 답할 것] {item}"
        else:
            api_msg = item
        history.append({"role": "user", "content": api_msg})
        try:
            text = ollama_call(history)
            # 한국어 입력인데 한국어 응답 없으면 재시도
            if is_korean(item) and not has_korean(text):
                retry = history + [
                    {"role": "assistant", "content": text},
                    {"role": "user", "content": "한국어로만 다시 답해줘."},
                ]
                text2 = ollama_call(retry)
                if has_korean(text2):
                    text = text2
            # 중국어 감지 시 재시도
            if has_chinese(text):
                retry = history + [
                    {"role": "assistant", "content": text},
                    {"role": "user", "content": "한국어로만 다시 답해줘. 중국어 사용 금지."},
                ]
                text2 = ollama_call(retry)
                if not has_chinese(text2):
                    text = text2
            history.append({"role": "assistant", "content": text})
            if len(history) > 20:
                history = history[-20:]
            resp_q.put(text)
        except Exception:
            resp_q.put("*연기 속으로 잠시 사라졌다 돌아오며* 마법이 흔들리는군... 다시 물어보게.")

# ── Wide-char aware truncation (Korean/CJK = 2 cols each) ────────────────────
def wc(ch):
    cp = ord(ch)
    if (0x1100 <= cp <= 0x115F or 0x2E80 <= cp <= 0x9FFF or
            0xAC00 <= cp <= 0xD7A3 or 0xF900 <= cp <= 0xFAFF or
            0xFF00 <= cp <= 0xFF60 or 0xFFE0 <= cp <= 0xFFE6):
        return 2
    return 1

def wtrunc(text, max_cols):
    w, out = 0, []
    for ch in text:
        cw = wc(ch)
        if w + cw > max_cols:
            out.append("…"); break
        out.append(ch); w += cw
    return "".join(out)

# ── Drawing helpers ───────────────────────────────────────────────────────────
def color_row(ri, line, glitch=False, horn_g=1.0):
    out = []
    for ch in line:
        if ch == " ": out.append(" "); continue
        is_h = ri in HORN_ROWS
        if glitch and random.random() < 0.12:
            out.append(CY + BD + random.choice(SPARKLES) + RESET); continue
        if is_h and ch in "▌▐":
            c = AU + BD if horn_g > 0.66 else (AY if horn_g > 0.33 else G3 + DM)
            out.append(c + ch + RESET)
        elif ch in EYE_CH:
            out.append(WH + BD + ch + RESET)
        elif ch in "▗▖▘▝▄▀▌▐█" and not is_h:
            out.append((G2 + BD if ri == 2 else G1) + ch + RESET)
        elif ch in "──◝◞ᴗω·◈":
            out.append(AU + ch + RESET)
        else:
            out.append(G1 + ch + RESET)
    return "".join(out)

def draw_face(rr, rc, fi, lim, glitch=False, horn_g=1.0):
    face = FACES[fi % len(FACES)]
    buf  = []
    for i, ln in enumerate(face):
        r = rr + i
        if r >= lim: break
        buf.append(mv(r, rc) + color_row(i, ln, glitch, horn_g))
    sys.stdout.write("".join(buf))

def draw_orbit(cx, cy, rad, t, col, ch, lim):
    _, cols = sz()
    buf = []
    for i in range(24):
        a = 2 * math.pi * i / 24 + t
        r = round(cy + rad * 0.42 * math.sin(a))
        c = round(cx + rad * math.cos(a))
        if 1 <= r < lim and 1 <= c <= cols:
            buf.append(mv(r, c) + col + DM + ch + RESET)
    sys.stdout.write("".join(buf))

def draw_sparks(sparks, lim):
    _, cols = sz()
    buf = []
    for x, y, ch, col, age, mx in sparks:
        yd = round(y - age * 0.4)
        if 1 <= yd < lim and 1 <= x <= cols:
            buf.append(mv(yd, x) + col + (BD if age < mx // 2 else DM) + ch + RESET)
    sys.stdout.write("".join(buf))

def draw_title(row, cols):
    t1 = "▗ ▗  L O K I  ▖ ▖"
    t2 = "▘▘  god of mischief  ▝▝"
    sys.stdout.write(mv(row,   (cols - len(t1)) // 2) + AU + BD + t1 + RESET)
    sys.stdout.write(mv(row+1, (cols - len(t2)) // 2) + G2 + DM + t2 + RESET)

def draw_chat(log, rows, cols, blink):
    cs = rows - CHAT_H + 1
    sys.stdout.write(mv(cs, 1) + G1 + DM + "─" * (cols - 1) + RESET + "\033[K")
    for r in range(cs + 1, rows):
        sys.stdout.write(mv(r, 1) + "\033[2K")
    visible = log[-(CHAT_H - 2):]
    for i, (role, text) in enumerate(visible):
        row = cs + 1 + i
        if row >= rows: break
        txt = wtrunc(text, cols - 12)
        if role == "you":
            sys.stdout.write(mv(row, 2) + CY + "  you" + G1 + " ▸ " + RESET + WH + txt + RESET + "\033[K")
        else:
            sys.stdout.write(mv(row, 2) + AU + BD + " Loki" + RESET + G2 + " ▸ " + RESET + G3 + txt + RESET + "\033[K")
    # ── DO NOT touch row `rows` — terminal echo handles user typing there ────

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    sys.stdout.write("\033[?1049h" + "\033[?7l" + "\033[2J")  # alt screen + no wrap + clear
    sys.stdout.flush()
    term_setup()

    threading.Thread(target=api_worker, daemon=True).start()
    threading.Thread(target=input_reader, daemon=True).start()

    sparks, spark_cd = [], 0
    tick          = 0
    log           = []
    thinking      = False
    talk_cooldown = 0
    chat_dirty    = True

    try:
        while True:
            rows, cols = sz()
            lim = rows - CHAT_H + 1
            t   = tick * 0.08

            # ── new user message ───────────────────────────────────────────────
            try:
                msg = input_q.get_nowait()
                if msg.strip() and not thinking:
                    log.append(("you", msg.strip()))
                    api_q.put(msg.strip())
                    thinking = True
                    chat_dirty = True
            except queue.Empty:
                pass

            # ── API response ──────────────────────────────────────────────────
            try:
                text = resp_q.get_nowait()
                log.append(("loki", text))
                thinking = False
                talk_cooldown = 50
                chat_dirty = True
            except queue.Empty:
                pass

            if talk_cooldown > 0:
                talk_cooldown -= 1

            # ── face state ────────────────────────────────────────────────────
            glitch = (tick % 90) in range(85, 90)
            if thinking:
                fi = 4
            elif talk_cooldown > 0:
                fi = 5
            elif glitch:
                fi = 0
            else:
                fi = (tick // 20) % 4

            horn_g = (math.sin(t * 2) + 1) / 2

            # ── loki position ─────────────────────────────────────────────────
            fh, fw = len(FACES[0]), len(FACES[0][0])
            rr = max(4, lim // 2 - fh // 2 + round(math.sin(t * 1.1) * 1.5))
            rc = max(1, cols // 2 - fw // 2 + round(math.sin(t * 0.6) * 2))

            # ── clear animation area only ─────────────────────────────────────
            buf = []
            for r in range(1, lim):
                buf.append(mv(r, 1) + "\033[2K")
            sys.stdout.write("".join(buf))

            # ── orbits ────────────────────────────────────────────────────────
            draw_orbit(cols // 2, lim // 2, 18, t,        G2,       "◈", lim)
            draw_orbit(cols // 2, lim // 2, 14, -t * 1.4, AU,       "ᛟ", lim)
            draw_orbit(cols // 2, lim // 2,  9,  t * 0.8, G3 + DM,  "·", lim)

            # ── horn sparkles ─────────────────────────────────────────────────
            if spark_cd <= 0:
                for hx in (rc + 1, rc + fw - 2):
                    for _ in range(random.randint(1, 2)):
                        sparks.append([hx + random.randint(-2, 2), rr + random.randint(-1, 1),
                                       random.choice(SPARKLES), random.choice([AU, AY, G3, CY]),
                                       0, random.randint(10, 18)])
                spark_cd = random.randint(4, 9)
            else:
                spark_cd -= 1
            sparks = [s for s in sparks if s[4] < s[5]]
            for s in sparks: s[4] += 1
            draw_sparks(sparks, lim)

            # ── face & title ──────────────────────────────────────────────────
            draw_face(rr, rc, fi, lim, glitch, horn_g)
            draw_title(max(1, rr - 3), cols)

            if thinking:
                dots = "." * (1 + (tick // 6) % 3)
                sys.stdout.write(mv(rr + fh + 1, cols // 2 - 6) +
                                 AU + f"생각 중{dots}   " + RESET)

            # ── chat UI (only when dirty or cursor blink) ─────────────────────
            if chat_dirty or (tick // 8) % 2 == 0:
                draw_chat(log, rows, cols, blink=(tick // 8) % 2 == 0)
                chat_dirty = False

            # ── 커서를 입력 줄로 복귀 (echo가 올바른 위치에 찍히게) ───────────
            sys.stdout.write(mv(rows, 1) + "\033[K" + G2 + " ❯ " + RESET)
            sys.stdout.flush()
            time.sleep(0.07)
            tick += 1

    except KeyboardInterrupt:
        pass
    finally:
        api_q.put(None)
        term_restore()
        sys.stdout.write(SHOW + "\033[?7h" + "\033[?1049l")
        print(f"{AU}{BD}▗ ▗  Loki fades into shadow  ▖ ▖{RESET}")

if __name__ == "__main__":
    main()
