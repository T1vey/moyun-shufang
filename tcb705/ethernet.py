"""Read-only IPv4/route checks; never reconfigure the board or scan a subnet."""
import ipaddress
import json
import socket
import subprocess


def endpoint(controller):
    values=[]
    for field in ('local_ip','remote_ip'):
        try:addr=ipaddress.IPv4Address(controller.get(field,''))
        except ipaddress.AddressValueError:raise ValueError('请配置有效的 IPv4：'+field)
        if addr.is_unspecified or addr.is_loopback or addr.is_multicast or int(addr)==0xffffffff:
            raise ValueError('需要实际网口的单播 IPv4：'+field)
        values.append(str(addr))
    if values[0]==values[1]:raise ValueError('板子和控制器 IP 不能相同')
    for field,default in (('port',8001),('web_port',8010)):
        value=controller.get(field,default)
        if type(value) is not int or not 1<=value<=65535:raise ValueError('无效端口：'+field)
    return tuple(values)


def inspect(controller,probe_ports=False):
    local,remote=endpoint(controller)
    def ip(*args):
        result=subprocess.run(['ip','-j']+list(args),capture_output=True,text=True,timeout=5,check=True)
        return json.loads(result.stdout)
    interfaces=ip('-4','address','show')
    owners=[row['ifname'] for row in interfaces if any(a.get('local')==local for a in row.get('addr_info',[]))]
    if not owners:raise ValueError('local_ip 未配置在板子的任何网口上；本工具不会修改网络')
    routes=ip('-4','route','get',remote,'from',local)
    if not routes or routes[0].get('dev') not in owners:
        raise ValueError('控制器路由未经过 local_ip 所在网口，请核对有线网段')
    result=dict(local_ip=local,remote_ip=remote,interface=routes[0]['dev'],read_only=True,
                route_ok=True,controller_verified=False,port_checks={})
    if probe_ports:
        for key in ('port','web_port'):
            port=controller.get(key,8001 if key=='port' else 8010)
            try:
                with socket.create_connection((remote,port),timeout=2,source_address=(local,0)):pass
                result['port_checks'][key]='tcp_connect_ok'
            except OSError:result['port_checks'][key]='unreachable_or_closed'
    return result
