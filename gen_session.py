#!/usr/bin/env python3
"""生成 Pyrogram Session String 的一键脚本

使用方法:
1. pip install pyrogram tgcrypto
2. python gen_session.py
3. 按提示输入手机号、验证码、2FA密码(如有)
4. 复制输出的 SESSION_STRING

获取 api_id/api_hash: https://my.telegram.org/apps
"""

from pyrogram import Client

api_id = 21614471
api_hash = "1f72a6b8575018b4cf19972b9c6dbbb8"

with Client("my_account", api_id=api_id, api_hash=api_hash) as app:
    session_string = app.export_session_string()
    print("\n" + "=" * 60)
    print("YOUR SESSION STRING:")
    print("=" * 60)
    print(session_string)
    print("=" * 60)
    print("\n请将此值填入 .env 的 TG_SESSION_STRING")
