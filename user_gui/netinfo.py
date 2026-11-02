"""本机网卡发现：找出手机能访问到的局域网 IPv4 地址及其子网（仅标准库）。

Windows 解析 ipconfig（兼容中英文输出），Linux 用 `ip -o -4 addr`，macOS 用 ifconfig；
都失败时退回到“默认路由探测 + 主机名解析”，子网按 /24 推测并标记 guessed。
"""
import ipaddress
import os
import re
import socket
import subprocess
import sys

VIRTUAL = re.compile(r"vEthernet|Hyper-V|VMware|VirtualBox|VBox|WSL|docker|br-|virbr|veth|vmnet|"
                     r"Loopback|Npcap|Bluetooth|蓝牙|isatap|Teredo", re.I)
VPN = re.compile(r"tailscale|zerotier|wireguard|wg\d|tun\d|utun|tap|OpenVPN|Clash|Meta|VPN", re.I)
IPV4 = re.compile(r"(\d{1,3}(?:\.\d{1,3}){3})")


def default_route_ip():
    """不发包，只让系统选路，得到默认出口网卡的 IP。"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return None


def _run(cmd):
    try:
        raw = subprocess.run(cmd, capture_output=True, timeout=4,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    for enc in (("oem", "mbcs", "gbk", "utf-8") if os.name == "nt" else ("utf-8",)):
        try:
            return raw.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", "replace")


def parse_ipconfig(text):
    """解析 Windows `ipconfig` 输出（中文或英文系统均可）。"""
    out, adapter, cur, in_gw = [], None, None, False
    for line in text.splitlines():
        if not line.strip():
            continue
        if not line[0].isspace():
            if line.rstrip().endswith(":"):
                adapter = re.sub(r"^.*?(adapter|适配器)\s*", "", line.rstrip()[:-1]).strip()
            cur, in_gw = None, False
            continue
        is_key = ":" in line and re.search(r"\.\s*:", line)
        if is_key:
            in_gw = "Gateway" in line or "网关" in line
        m = IPV4.search(line)
        if not m or adapter is None:
            continue
        ip = m.group(1)
        if is_key and ("IPv4" in line or "IP Address" in line or "IP 地址" in line):
            cur = dict(ip=ip, mask=None, gateway=False, adapter=adapter)
            out.append(cur)
        elif cur and in_gw:
            if ip != "0.0.0.0":
                cur["gateway"] = True
        elif cur and cur["mask"] is None and ip.startswith("255."):
            cur["mask"] = ip
    return [dict(ip=r["ip"], prefix=_mask_to_prefix(r["mask"]), adapter=r["adapter"], gateway=r["gateway"])
            for r in out]


def parse_ip_addr(text):
    """解析 Linux `ip -o -4 addr show` 输出。"""
    out = []
    for m in re.finditer(r"^\d+:\s+(\S+)\s+inet\s+(\d+\.\d+\.\d+\.\d+)/(\d+)", text, re.M):
        out.append(dict(ip=m.group(2), prefix=int(m.group(3)), adapter=m.group(1), gateway=None))
    return out


def parse_ifconfig(text):
    """解析 macOS / BSD `ifconfig` 输出。"""
    out, adapter = [], None
    for line in text.splitlines():
        h = re.match(r"^(\S+?):\s", line)
        if h:
            adapter = h.group(1)
        m = re.search(r"inet (\d+\.\d+\.\d+\.\d+) netmask (0x[0-9a-f]+|\d+\.\d+\.\d+\.\d+)", line)
        if m and adapter:
            mask = m.group(2)
            prefix = bin(int(mask, 16)).count("1") if mask.startswith("0x") else _mask_to_prefix(mask)
            out.append(dict(ip=m.group(1), prefix=prefix, adapter=adapter, gateway=None))
    return out


def _mask_to_prefix(mask):
    try:
        return ipaddress.IPv4Network(f"0.0.0.0/{mask}").prefixlen
    except (ValueError, TypeError):
        return None


def classify(ip, adapter=""):
    a = ipaddress.IPv4Address(ip)
    if a.is_loopback:
        return "loopback"
    if a.is_link_local:
        return "link-local"
    if VIRTUAL.search(adapter or ""):
        return "virtual"
    if VPN.search(adapter or "") or ipaddress.IPv4Address(ip) in ipaddress.IPv4Network("100.64.0.0/10"):
        return "vpn"
    if a.is_private:
        return "lan"
    return "public"


def interfaces():
    """返回按“手机最可能访问到”排序的网卡列表。"""
    if sys.platform.startswith("win"):
        rows = parse_ipconfig(_run(["ipconfig"]))
    elif sys.platform == "darwin":
        rows = parse_ifconfig(_run(["ifconfig"]))
    else:
        rows = parse_ip_addr(_run(["ip", "-o", "-4", "addr", "show"]))
    default = default_route_ip()
    known = {r["ip"] for r in rows}
    extra = [default] if default else []
    try:
        extra += [i[4][0] for i in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)]
    except OSError:
        pass
    for ip in extra:
        if ip and ip not in known:
            known.add(ip)
            rows.append(dict(ip=ip, prefix=None, adapter="", gateway=None))
    return rank(rows, default)


def rank(rows, default=None):
    out = []
    for r in rows:
        try:
            kind = classify(r["ip"], r.get("adapter", ""))
        except ValueError:
            continue
        if kind == "loopback":
            continue
        guessed = r.get("prefix") is None
        prefix = 24 if guessed else r["prefix"]
        net = ipaddress.IPv4Network(f"{r['ip']}/{prefix}", strict=False)
        score = {"lan": 50, "vpn": 10, "public": 5, "virtual": -40, "link-local": -60}[kind]
        if r["ip"] == default:
            score += 100
        if r.get("gateway"):
            score += 30
        # The Z20's eth0 link is the development PC; phones use its USB WLAN.
        # Prefer an actual wireless interface even when eth0 owns a default route.
        wireless = bool(re.search(r'(^wl|wi[- ]?fi|wlan|无线)', r.get('adapter', ''), re.I))
        if wireless and kind == 'lan':
            score += 250
        if r["ip"].startswith("192.168."):
            score += 3
        out.append(dict(ip=r["ip"], prefix=prefix, cidr=str(net), guessed=guessed, adapter=r.get("adapter") or "",
                        kind=kind, gateway=r.get("gateway"), default=r["ip"] == default, score=score,
                        wireless=wireless))
    out.sort(key=lambda x: -x["score"])
    return out


def manual_interface(ip, adapter="手动指定"):
    """--host-ip / SO101_HOST_IP 指定的地址。"""
    ipaddress.IPv4Address(ip)  # 校验
    r = rank([dict(ip=ip, prefix=None, adapter=adapter, gateway=None)])
    if r:
        r[0].update(manual=True, score=1000)
        return r[0]
    return dict(ip=ip, prefix=None, cidr=ip, guessed=True, adapter=adapter, kind="loopback", manual=True, score=1000)


def same_subnet(client_ip, iface):
    try:
        return ipaddress.IPv4Address(client_ip) in ipaddress.IPv4Network(iface["cidr"], strict=False)
    except (ValueError, KeyError):
        return False


def is_lan_client(ip):
    """手机来源是否为局域网 / 本机地址（开放模式只放行这些）。"""
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if getattr(a, "ipv4_mapped", None):
        a = a.ipv4_mapped
    return a.is_private or a.is_loopback or a.is_link_local or a in ipaddress.ip_network("100.64.0.0/10")
