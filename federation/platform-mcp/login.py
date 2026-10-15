"""User-driven logins. Own profiles only; never attach to a personal browser."""
import asyncio
import fcntl
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from federation.platform_mcp_registry import RUNTIME, private_path, write_private
from datetime import datetime,timezone

provider=sys.argv[1]
def state(phase,message):
    write_private(private_path(provider+'-login-status.json'),{'state':phase,'message':message,'updated_at':datetime.now(timezone.utc).isoformat()})

async def bilibili():
    from bilibili_api.login_v2 import QrCodeLogin,QrCodeLoginEvents
    qr=QrCodeLogin()
    await qr.generate_qrcode()
    path=private_path('bilibili-login.png')
    path.write_bytes(qr.get_qrcode_picture().content);path.chmod(0o600)
    state('waiting','请用哔哩哔哩手机 App 扫描下方二维码，并在手机确认。')
    for _ in range(90):
        event=await qr.check_state()
        if event==QrCodeLoginEvents.DONE:
            cookies=qr.get_credential().get_cookies()
            write_private(private_path('bilibili.json'),{'sessdata':cookies.get('SESSDATA'),'bili_jct':cookies.get('bili_jct'),'buvid3':cookies.get('buvid3'),'dedeuserid':cookies.get('DedeUserID')})
            return
        if event==QrCodeLoginEvents.TIMEOUT:raise TimeoutError()
        await asyncio.sleep(2)
    raise TimeoutError()

async def browser(provider):
    from playwright.async_api import async_playwright
    # This exact Tieba profile is also used by the installed MCP adapter.
    profile=RUNTIME/'private/mediacrawler/browser_profiles/tieba_user_data_dir' if provider=='tieba' else RUNTIME/'private/douyin-login-browser'
    profile.mkdir(parents=True,exist_ok=True,mode=0o700)
    async with async_playwright() as p:
        context=await p.chromium.launch_persistent_context(str(profile),channel='chrome',headless=False)
        try:
            page=await context.new_page()
            await page.goto('https://tieba.baidu.com' if provider=='tieba' else 'https://www.douyin.com',wait_until='domcontentloaded',timeout=45000)
            state('waiting','请在新打开的独立 Chrome 窗口中点击登录并扫码；完成后会自动保存。')
            for _ in range(150):
                cookies=await context.cookies()
                valid=[c for c in cookies if c['domain'].lstrip('.').endswith('baidu.com' if provider=='tieba' else 'douyin.com')]
                names={c['name'] for c in valid}
                if ('BDUSS' in names if provider=='tieba' else bool(names & {'sessionid','sessionid_ss'})):
                    if provider=='tieba':
                        write_private(private_path('tieba-cookies.json'), valid)
                        write_private(private_path('tieba-login.json'),{'saved':True})
                    else:
                        path=private_path('douyin-cookies.txt');temp=path.with_suffix('.tmp')
                        fd=os.open(str(temp),os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
                        with os.fdopen(fd,'w') as f:f.write('; '.join(c['name']+'='+c['value'] for c in valid))
                        os.replace(temp,path);path.chmod(0o600)
                    return
                await asyncio.sleep(2)
            raise TimeoutError()
        finally:await context.close()

async def main():
    state('starting','正在准备独立登录入口…')
    await (bilibili() if provider=='bilibili' else browser(provider))
    state('saved','登录信息已保存，可以继续原来的问题；资料读取结果以实际调用为准。')

if __name__=='__main__':
    with private_path(provider+'-session.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:sys.exit(0)
        try:asyncio.run(asyncio.wait_for(main(),360))
        except Exception as exc:state('failed','登录超时或窗口已关闭，请重新点击登录。' if isinstance(exc,TimeoutError) else '登录未完成，请检查网络后重试。')
