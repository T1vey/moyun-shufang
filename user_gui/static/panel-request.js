"use strict";
// Bound both response headers and JSON decoding. Never retry a motion request.
window.PanelRequest={json:function(url,options,timeoutMs){
  var controller=typeof AbortController!=="undefined"?new AbortController():null;
  var opts=Object.assign({},options||{}),timer;
  if(controller)opts.signal=controller.signal;
  var deadline=new Promise(function(_resolve,reject){
    timer=setTimeout(function(){
      var writing=String(opts.method||"GET").toUpperCase()!=="GET";
      reject(Error(writing?"请求超时，结果尚未确认。请返回主界面查看任务状态，勿重复提交。":"读取超时，请检查连接后重试。"));
      if(controller)controller.abort();
    },timeoutMs||15000);
  });
  var work=Promise.resolve().then(function(){return fetch(url,opts);}).then(function(response){
    return response.json().then(function(data){
      if(!response.ok)throw Error(data.error||"操作失败");
      return data;
    });
  });
  return Promise.race([work,deadline]).then(function(data){clearTimeout(timer);return data;},function(error){clearTimeout(timer);throw error;});
}};
