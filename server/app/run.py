import os
import uvicorn

if __name__ == '__main__':
    level=os.getenv('LOG_LEVEL','info').lower()
    if level not in ('info','warning','error','critical'):level='info'
    uvicorn.run('app.main:app',host='0.0.0.0',port=8000,workers=1,access_log=False,proxy_headers=False,log_level=level,ws_max_size=4096,ws_max_queue=4)
