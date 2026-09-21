/* Same-origin API authentication. Tokens live only in memory, never URLs/storage. */
(()=>{
  const nativeFetch=window.fetch.bind(window);
  let pendingToken=null;
  function forgetToken(){pendingToken=null;}
  function localToken(){
    if(!pendingToken){
      pendingToken=(async()=>{
        if(!['http:','https:'].includes(location.protocol))throw new Error('Open the dashboard from the local server, not a file.');
        const response=await nativeFetch(new URL('/api/local-session',location.origin),{
          headers:{'X-AMS-Bootstrap':'1'},cache:'no-store',credentials:'same-origin',redirect:'error'
        });
        if(!response.ok)throw new Error('Local dashboard authentication failed.');
        const data=await response.json();
        if(!data.ok||typeof data.token!=='string'||!data.token)throw new Error('Local dashboard token unavailable.');
        return data.token;
      })().catch(error=>{forgetToken();throw error;});
    }
    return pendingToken;
  }
  window.amsLocalToken=localToken;
  window.amsForgetLocalToken=forgetToken;
  window.amsFetch=async(input,options={})=>{
    const request=new Request(input,options);
    const url=new URL(request.url,location.href);
    if(url.origin!==location.origin||!url.pathname.startsWith('/api/'))throw new Error('Dashboard API requests must stay on the same origin.');
    const token=await localToken();
    const headers=new Headers(request.headers);
    headers.set('X-AMS-Local-Token',token);
    const response=await nativeFetch(new Request(request,{headers,credentials:'same-origin',redirect:'error',cache:'no-store'}));
    // Never replay a write (or a settings GET with protocol writes) automatically.
    if(response.status===403)forgetToken();
    return response;
  };
})();
