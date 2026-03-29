#!/usr/bin/env python3
import configparser
import logging
import os
import re
import socket
import subprocess
import time
from datetime import datetime
from pathlib import Path

CONFIG_PATH = Path(__file__).with_name("config.ini")

BROTHER_HDR_LEN = 14
END_MARKER = b"\x00\x21\x01\x00\x00\x20"
recent_jobs = {}

DEFAULT_SSP = {
    "PSRC": "AUTO",
    "CLR": "C24BIT",
    "AREA": "NORMAL",
    "MRGN": "0,0,0,0",
    "DPLX": "OFF",
    "BRIT": "50",
    "CONT": "50",
    "COMP": "JPEG",
    "JSF": "420",
    "IPRC": "NORMAL",
    "PTYPE": "NORMAL",
    "PAGE": "0",
    "LONG": "OFF",
    "CARR": "OFF",
    "RMGC": "OFF",
    "DTDF": "OFF",
    "DT4V": "OFF",
    "DSKW": "OFF",
    "LSMD": "OFF",
    "RMBP": "OFF",
    "RMMR": "OFF",
    "GMMA": "OFF",
    "TONE": "OFF",
    "QTFD": "OFF",
    "ATCN": "OFF",
    "ATCRP": "OFF",
}

DEFAULT_XSC = {
    "MODE": "NORMAL",
}

ALLOWED_RESOLUTIONS = {100, 150, 200, 300, 400, 600, 1200, 2400, 4800, 9600}


def load_config() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser(interpolation=None)
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Cant find config.ini: {CONFIG_PATH}")
    cfg.read(CONFIG_PATH, encoding="utf-8")
    return cfg


def setup_logging(cfg: configparser.ConfigParser):
    level_name = cfg.get("general", "log_level", fallback="INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(message)s")


def parse_message(msg: str) -> dict:
    result = {}
    for part in msg.strip().split(";"):
        if not part or "=" not in part:
            continue
        key, value = part.split("=", 1)
        result[key] = value.strip('"')
    return result


def sanitize_path_component(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return "Unbekannt"
    value = re.sub(r"[\/\\]+", "_", value)
    value = re.sub(r"[^A-Za-z0-9._ -]+", "_", value)
    value = value.strip(" .")
    return value or "Unbekannt"


def recv_some(sock: socket.socket, timeout: float) -> bytes:
    sock.settimeout(timeout)
    try:
        return sock.recv(65535)
    except socket.timeout:
        return b""
    except (ConnectionResetError, OSError):
        return b""


def build_q() -> bytes:
    return b"\x1bQ\n\x80"


def build_qdi() -> bytes:
    return b"\x1bQDI\n\x80"


def build_gkp() -> bytes:
    return b"\x1bGKP\n\x80"


def build_ckd(psrc: str = "ADF") -> bytes:
    return f"\x1bCKD\nPSRC={psrc}\n".encode("ascii", errors="ignore") + b"\x80"


def parse_area(area_str: str) -> tuple[int, int, int, int]:
    parts = [p.strip() for p in area_str.split(",")]
    if len(parts) != 4:
        raise ValueError(f"Wrong base_area: {area_str}")
    return tuple(int(p) for p in parts)


def scale_area(base_area: tuple[int, int, int, int], resolution: int) -> str:
    factor = resolution / 100.0
    scaled = [int(round(v * factor)) for v in base_area]
    return ",".join(str(v) for v in scaled)


def get_section_name(func: str) -> str:
    return f"func:{(func or 'FILE').upper()}"


def get_func_config(cfg: configparser.ConfigParser, func: str) -> dict:
    sec = get_section_name(func)

    folder = cfg.get(sec, "folder", fallback=(func or "FILE").title())
    user_subdir = cfg.getboolean(sec, "user_subdir", fallback=True)
    probe_psrc = cfg.get(sec, "probe_psrc", fallback="ADF")

    resolution = cfg.getint(sec, "resolution", fallback=100)
    if resolution not in ALLOWED_RESOLUTIONS:
        raise ValueError(f"Cant reference resolution {resolution} in [{sec}]")

    base_area_str = cfg.get(sec, "base_area", fallback="12,4,839,1169")
    base_area = parse_area(base_area_str)
    xsc_area = scale_area(base_area, resolution)
    reso_str = f"{resolution},{resolution}"

    ssp = dict(DEFAULT_SSP)
    xsc = dict(DEFAULT_XSC)

    for key in DEFAULT_SSP:
        ssp[key] = cfg.get(sec, f"ssp_{key.lower()}", fallback=ssp[key])
    for key in DEFAULT_XSC:
        xsc[key] = cfg.get(sec, f"xsc_{key.lower()}", fallback=xsc[key])

    ssp["RESO"] = reso_str
    xsc["RESO"] = reso_str
    xsc["AREA"] = xsc_area

    return {
        "folder": folder,
        "user_subdir": user_subdir,
        "probe_psrc": probe_psrc,
        "resolution": resolution,
        "base_area": base_area_str,
        "ssp": ssp,
        "xsc": xsc,
    }


def build_output_dir(cfg: configparser.ConfigParser, user: str, func: str) -> Path:
    base_output_dir = Path(cfg.get("general", "base_output_dir", fallback="/mnt/Media/Scans"))
    fcfg = get_func_config(cfg, func)

    folder = sanitize_path_component(fcfg["folder"])
    username = sanitize_path_component(user)

    if fcfg["user_subdir"]:
        outdir = base_output_dir / username / folder
    else:
        outdir = base_output_dir / folder

    outdir.mkdir(parents=True, exist_ok=True)
    return outdir


def build_ssp(user: str, ssp_map: dict) -> bytes:
    lines = ["\x1bSSP", "OS=LNX"]
    for k, v in ssp_map.items():
        lines.append(f"{k}={v}")
    lines.append(f"USER={user}")
    text = "\n".join(lines) + "\n"
    return text.encode("ascii", errors="ignore") + b"\x80"


def build_xsc(xsc_map: dict) -> bytes:
    lines = ["\x1bXSC"]
    for k, v in xsc_map.items():
        lines.append(f"{k}={v}")
    text = "\n".join(lines) + "\n"
    return text.encode("ascii", errors="ignore") + b"\x80"


def connect_for_scan_ready(printer_ip: str, scan_port: int, retries: int = 20, delay: float = 0.5):
    last_err = None
    for _ in range(retries):
        try:
            sock = socket.create_connection((printer_ip, scan_port), timeout=5)
        except OSError as e:
            last_err = e
            time.sleep(delay)
            continue

        try:
            banner = recv_some(sock, 1.0)
            if banner.startswith(b"+OK 200"):
                return sock
            sock.close()
            time.sleep(delay)
        except OSError as e:
            last_err = e
            try:
                sock.close()
            except Exception:
                pass
            time.sleep(delay)

    if last_err:
        raise last_err
    raise RuntimeError("Printer not ready")


def run_probe_phase(cfg: configparser.ConfigParser, printer_ip: str, func: str):
    scan_port = cfg.getint("device", "scan_port", fallback=54921)
    fcfg = get_func_config(cfg, func)

    sock = connect_for_scan_ready(printer_ip, scan_port, retries=12, delay=0.25)
    with sock:
        recv_some(sock, 0.2)
        for pkt in (build_q(), build_qdi(), build_gkp(), build_ckd(fcfg["probe_psrc"])):
            sock.sendall(pkt)
            recv_some(sock, 0.8)

    time.sleep(cfg.getfloat("timing", "post_probe_sleep", fallback=0.35))


def is_brother_header(data: bytes, pos: int) -> bool:
    if pos + BROTHER_HDR_LEN > len(data):
        return False
    return (
        data[pos + 0] == 0x00 and
        data[pos + 1] == 0x02 and
        data[pos + 3] == 0x00 and
        data[pos + 4] == 0x15 and
        data[pos + 5] == 0x00 and
        data[pos + 12] == 0x00 and
        data[pos + 13] == 0x00
    )


def decode_brother_blocks(raw: bytes) -> bytes:
    start = -1
    for i in range(len(raw) - BROTHER_HDR_LEN + 1):
        if is_brother_header(raw, i):
            start = i
            break

    if start < 0:
        return b""

    out = bytearray()
    i = start

    while i < len(raw):
        if raw.startswith(END_MARKER, i):
            break
        if is_brother_header(raw, i):
            i += BROTHER_HDR_LEN
            continue
        out.append(raw[i])
        i += 1

    return bytes(out)


def trim_after_end_marker(data: bytes) -> bytes:
    idx = data.find(END_MARKER)
    return data[:idx] if idx >= 0 else data


def extract_complete_jpegs(data: bytes) -> list[bytes]:
    pages = []
    pos = 0
    while True:
        soi = data.find(b"\xff\xd8", pos)
        if soi < 0:
            break
        eoi = data.find(b"\xff\xd9", soi + 2)
        if eoi < 0:
            break
        pages.append(data[soi:eoi + 2])
        pos = eoi + 2
    return pages


def collect_scan_stream(cfg: configparser.ConfigParser, sock: socket.socket, user: str, func: str) -> bytes:
    fcfg = get_func_config(cfg, func)
    raw = bytearray()

    sock.sendall(build_ssp(user, fcfg["ssp"]))
    rsp = recv_some(sock, 0.8)
    if rsp:
        raw.extend(rsp)

    sock.sendall(build_xsc(fcfg["xsc"]))
    rsp = recv_some(sock, 0.8)
    if rsp:
        raw.extend(rsp)

    first_data_deadline = time.time() + cfg.getfloat("timing", "first_data_timeout", fallback=30.0)
    got_scan_data = False

    while time.time() < first_data_deadline:
        chunk = recv_some(sock, 1.0)
        if chunk:
            raw.extend(chunk)
            if b"\xff\xd8" in raw:
                got_scan_data = True
                break

    if not got_scan_data:
        return bytes(raw)

    quiet_timeout = cfg.getfloat("timing", "quiet_timeout", fallback=5.0)
    hard_deadline = time.time() + cfg.getfloat("timing", "hard_deadline", fallback=120.0)
    last_data = time.time()

    while time.time() < hard_deadline:
        chunk = recv_some(sock, 1.0)
        if chunk:
            raw.extend(chunk)
            last_data = time.time()
        elif time.time() - last_data > quiet_timeout:
            break

    while True:
        chunk = recv_some(sock, 0.2)
        if not chunk:
            break
        raw.extend(chunk)

    return bytes(raw)


def save_pages(outdir: Path, func: str, pages: list[bytes]) -> list[Path]:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    written = []
    for i, page in enumerate(pages, start=1):
        out = outdir / f"{func.lower()}_{ts}_p{i}.jpg"
        out.write_bytes(page)
        written.append(out)
    return written


def save_debug_file(outdir: Path, name: str, suffix: str, data: bytes) -> Path:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = outdir / f"{name.lower()}_{ts}.{suffix}"
    out.write_bytes(data)
    return out


def run_post_hook(cfg: configparser.ConfigParser, user: str, func: str, outdir: Path, files: list[Path]):
    command = cfg.get("hooks", "post_scan_command", fallback="").strip()
    if not command:
        return

    env = os.environ.copy()
    env["SCAN_USER"] = user
    env["SCAN_FUNC"] = func
    env["SCAN_OUTDIR"] = str(outdir)
    env["SCAN_PAGE_COUNT"] = str(len(files))
    env["SCAN_TIMESTAMP"] = datetime.now().strftime("%Y%m%d-%H%M%S")
    env["SCAN_FILES"] = "\n".join(str(p) for p in files)
    env["SCAN_FIRST_FILE"] = str(files[0]) if files else ""
    env["SCAN_LAST_FILE"] = str(files[-1]) if files else ""

    logging.info("Starting Post-Scan-Hook: %s", command)
    proc = subprocess.run(command, shell=True, env=env, capture_output=True, text=True)

    if proc.stdout.strip():
        logging.info("Hook stdout:\n%s", proc.stdout.strip())
    if proc.stderr.strip():
        logging.info("Hook stderr:\n%s", proc.stderr.strip())
    if proc.returncode != 0:
        logging.warning("Hook closed with exit status %s", proc.returncode)


def run_scan(cfg: configparser.ConfigParser, printer_ip: str, user: str, func: str):
    outdir = build_output_dir(cfg, user, func)
    scan_port = cfg.getint("device", "scan_port", fallback=54921)
    fcfg = get_func_config(cfg, func)

    logging.info("Use: RESO=%s and XSC_AREA=%s", fcfg["ssp"]["RESO"], fcfg["xsc"]["AREA"])

    run_probe_phase(cfg, printer_ip, func)

    with connect_for_scan_ready(printer_ip, scan_port, retries=20, delay=0.35) as sock:
        raw_stream = collect_scan_stream(cfg, sock, user, func)

    debug_save_raw = cfg.getboolean("debug", "save_raw_stream", fallback=False)
    debug_save_payload = cfg.getboolean("debug", "save_payload", fallback=False)

    if debug_save_raw:
        raw_file = save_debug_file(outdir, f"{func}_fullstream", "raw", raw_stream)
        logging.info("Saved full raw stream: %s", raw_file)

    payload = trim_after_end_marker(decode_brother_blocks(raw_stream))

    if debug_save_payload:
        payload_file = save_debug_file(outdir, f"{func}_payload", "bin", payload)
        logging.info("Decoded payload saved: %s", payload_file)

    logging.info("Payload: %d Bytes, SOI=%d, EOI=%d", len(payload), payload.count(b"\xff\xd8"), payload.count(b"\xff\xd9"))

    pages = extract_complete_jpegs(payload)
    if not pages:
        logging.warning("no jpeg data received")
        return

    written = save_pages(outdir, func, pages)
    logging.info("Scan saved: %s", ", ".join(str(p) for p in written))

    run_post_hook(cfg, user, func, outdir, written)


def is_duplicate_job(fields: dict, window_sec: int = 30) -> bool:
    global recent_jobs

    regid = fields.get("REGID", "")
    seq = fields.get("SEQ", "")
    func = fields.get("FUNC", "")
    key = (regid, seq, func)

    now = time.time()
    recent_jobs = {k: ts for k, ts in recent_jobs.items() if now - ts < window_sec}

    if key in recent_jobs:
        return True

    recent_jobs[key] = now
    return False


def main():
    cfg = load_config()
    setup_logging(cfg)

    base_output_dir = Path(cfg.get("general", "base_output_dir", fallback="~/"))
    base_output_dir.mkdir(parents=True, exist_ok=True)

    udp_port = cfg.getint("device", "udp_port", fallback=54925)
    printer_ip = cfg.get("device", "printer_ip", fallback="192.168.0.253")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", udp_port))

    logging.info("Waiting for Brother-Trigger on UDP %d", udp_port)

    while True:
        data, addr = sock.recvfrom(4096)
        msg = data.decode("utf-8", errors="replace").strip()
        logging.info("UDP from %s: %s", addr, msg)

        fields = parse_message(msg)
        if fields.get("BUTTON") != "SCAN":
            continue

        func = (fields.get("FUNC") or "FILE").upper()
        user = fields.get("USER", "")

        if is_duplicate_job(fields):
            logging.info("Ignoring doubled trigger: REGID=%s SEQ=%s FUNC=%s", fields.get("REGID", ""), fields.get("SEQ", ""), func)
            continue

        try:
            logging.info("Startup Scan for USER=%s FUNC=%s", user, func)
            run_scan(cfg, printer_ip, user, func)
        except Exception as e:
            logging.error("Error: %s", e)


if __name__ == "__main__":
    main()

