"""ArmVision web-read-pose protocol, restricted to login + feedback reads.

Source: backend/utils/tianlian_xoip_sender.py. No enable, jog, variable-write,
program-upload or start endpoint is reachable from this module.
"""
import hashlib
import ipaddress
import json
import math
import os
import time
import urllib.parse
import urllib.request

def read_world(controller,robot_id):
    ip=ipaddress.ip_address(controller['remote_ip'])
    if ip.version!=4:raise ValueError('控制器地址需为 IPv4')
    port=controller.get('web_port',8010)
    if type(port) is not int or not 1<=port<=65535:raise ValueError('无效控制器 Web 端口')
    if type(robot_id) is not int or not 1<=robot_id<=32:raise ValueError('无效机器人 ID')
    base='http://%s:%d'%(ip,port)
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def request(path,data=None,token=None):
        headers={'Content-Type':'application/json','Connection':'close'}
        if token:headers['Authorization']='Bearer '+token
        body=None if data is None else json.dumps(data).encode('utf-8')
        req=urllib.request.Request(base+path,data=body,headers=headers)
        with opener.open(req,timeout=3) as response:
            raw=response.read(1024*1024+1)
        if len(raw)>1024*1024:raise ValueError('控制器返回数据过大')
        try:text=raw.decode('utf-8-sig')
        except UnicodeDecodeError:text=raw.decode('gb18030')
        result=json.loads(text)
        if not isinstance(result,dict) or result.get('code')!=0:raise ValueError('控制器拒绝读取请求 '+path.split('?')[0])
        return result
    # Original software defaults; deployments can override without storing or
    # returning credentials in the GUI config or job result.
    username=os.environ.get('TCB_WEB_USER','szhc')
    password=os.environ.get('TCB_WEB_PASSWORD','szhcszhc')
    login=request('/api/user/login',{'name':username,'password':hashlib.md5(password.encode('utf-8')).hexdigest()})
    data=login.get('data',{});token=login.get('token') or (data.get('token') if isinstance(data,dict) else None)
    if not isinstance(token,str) or not token:raise ValueError('控制器登录未返回令牌')
    pose=[];started=time.monotonic()
    for index in range(6):
        name='r_world_fb_pos_%d_%d_'%(robot_id,index)
        item=request('/api/var/byname?name='+urllib.parse.quote(name),token=token).get('data')
        if not isinstance(item,dict) or item.get('value') in (None,''):raise ValueError('控制器缺少反馈 '+name)
        if isinstance(item['value'],bool):raise ValueError('无效反馈 '+name)
        value=float(item['value'])
        if not math.isfinite(value):raise ValueError('控制器反馈不是有限数 '+name)
        pose.append(value)
    return dict(read_only=True,physical_motion=False,robot_id=robot_id,
        world_mm_deg=pose,source='armvision_web_world_feedback',
        coordinate_frame='controller_world',units=['mm','mm','mm','deg','deg','deg'],
        controller_timestamp_available=False,host_read_duration_s=time.monotonic()-started,
        note='与原软件一样逐项读取；采集期间须保持机械臂静止。')
