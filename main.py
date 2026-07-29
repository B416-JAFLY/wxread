# main.py 主逻辑：包括字段拼接、模拟请求
import json
import time
import random
import logging
import hashlib
import os
import requests
import urllib.parse
from push import push
from log_utils import setup_logging
from config import data, headers, cookies, READ_NUM, PUSH_METHOD, book, chapter


# 加密盐及其它默认值
KEY = "3c5c8717f3daf09iop3423zafeqoi"
READ_URL = "https://weread.qq.com/web/book/read"
RENEW_URL = "https://weread.qq.com/web/login/renewal"
FIX_SYNCKEY_URL = "https://weread.qq.com/web/book/chapterInfos"
COOKIE_DATA_VARIANTS = [{"rq": "%2Fweb%2Fbook%2Fread", "ql": False},{"rq": "%2Fweb%2Fbook%2Fread", "ql": True},{"rq": "%2Fweb%2Fbook%2Fread"},]
MAX_SESSION_RECOVERIES = 2


class SessionExpiredError(RuntimeError):
    """微信读书登录态无法继续自动续签。"""


def encode_data(data):
    """数据编码"""
    return '&'.join(f"{k}={urllib.parse.quote(str(data[k]), safe='')}" for k in sorted(data.keys()))


def cal_hash(input_string):
    """计算哈希值"""
    _7032f5 = 0x15051505
    _cc1055 = _7032f5
    length = len(input_string)
    _19094e = length - 1

    while _19094e > 0:
        _7032f5 = 0x7fffffff & (_7032f5 ^ ord(input_string[_19094e]) << (length - _19094e) % 30)
        _cc1055 = 0x7fffffff & (_cc1055 ^ ord(input_string[_19094e - 1]) << _19094e % 30)
        _19094e -= 2

    return hex(_7032f5 + _cc1055)[2:].lower()

session = requests.Session()
session.headers.update(headers)
session.cookies.update(cookies)


def renew_session():
    """续签短期会话，并保留服务端返回的全部登录 Cookie。"""
    for cookie_data in COOKIE_DATA_VARIANTS:
        try:
            response = session.post(
                RENEW_URL,
                data=json.dumps(cookie_data, separators=(',', ':')),
                timeout=15,
            )
            response.raise_for_status()
            result = response.json()
            renewed = response.cookies.get_dict()
            if result.get("succ") == 1 and "wr_skey" in renewed:
                cookies.update(renewed)
                session.cookies.clear()
                session.cookies.update(cookies)
                logging.info(
                    "会话续签成功，已更新 Cookie：%s",
                    ", ".join(sorted(renewed)),
                )
                return renewed
        except requests.RequestException as exc:
            logging.warning("会话续签请求失败：%s", exc)
        except ValueError:
            logging.warning("会话续签返回了无法解析的响应。")

    raise SessionExpiredError(
        "微信读书登录态已失效，自动续签失败；请重新登录并更新 WXREAD_CURL_BASH。"
    )

def fix_no_synckey():
    response = session.post(
        FIX_SYNCKEY_URL,
        data=json.dumps({"bookIds":["3300060341"]}, separators=(',', ':')),
        timeout=15,
    )
    response.raise_for_status()

refresh_print = setup_logging()

def workflow_run_url():
    server = os.getenv("GITHUB_SERVER_URL")
    repository = os.getenv("GITHUB_REPOSITORY")
    run_id = os.getenv("GITHUB_RUN_ID")
    if server and repository and run_id:
        return f"{server}/{repository}/actions/runs/{run_id}"
    return ""


def notify_result(content, is_success):
    if PUSH_METHOD in (None, ""):
        logging.info("未配置推送渠道，跳过推送。")
        return False
    logging.info("开始推送执行结果...")
    delivered = push(content, PUSH_METHOD, is_success=is_success)
    if not delivered:
        logging.warning("结果推送失败，但不改变阅读任务的执行结果。")
    return delivered


def run():
    index = 1
    last_time = int(time.time()) - 30
    recoveries = 0

    try:
        logging.info("开始续签微信读书会话。")
        renew_session()
        logging.info("一共需要阅读 %d 次。", READ_NUM)

        while index <= READ_NUM:
            data.pop("s", None)
            data["b"] = random.choice(book)
            data["c"] = random.choice(chapter)
            this_time = int(time.time())
            data["ct"] = this_time
            data["rt"] = this_time - last_time
            data["ts"] = int(this_time * 1000) + random.randint(0, 1000)
            data["rn"] = random.randint(0, 1000)
            data["sg"] = hashlib.sha256(
                f"{data['ts']}{data['rn']}{KEY}".encode()
            ).hexdigest()
            data["s"] = cal_hash(encode_data(data))

            refresh_print(
                f"阅读进度: 第 {index}/{READ_NUM} 次，"
                f"已完成 {(index - 1) * 0.5:.1f} 分钟"
            )
            logging.debug("data: %s", data)

            try:
                response = session.post(
                    READ_URL,
                    data=json.dumps(data, separators=(",", ":")),
                    timeout=20,
                )
                response.raise_for_status()
                result = response.json()
            except (requests.RequestException, ValueError) as exc:
                logging.warning("阅读请求失败：%s", exc)
                result = {}

            logging.debug("response: %s", result)

            if result.get("succ") == 1 and "synckey" in result:
                last_time = this_time
                index += 1
                recoveries = 0
                time.sleep(30)
                refresh_print(
                    f"阅读进度: 第 {min(index, READ_NUM + 1) - 1}/{READ_NUM} 次，"
                    f"已完成 {(index - 1) * 0.5:.1f} 分钟"
                )
                continue

            recoveries += 1
            if recoveries > MAX_SESSION_RECOVERIES:
                raise SessionExpiredError(
                    "连续恢复登录态失败；请重新登录微信读书并更新 WXREAD_CURL_BASH。"
                )

            if result.get("succ") == 1:
                logging.warning("响应缺少 synckey，尝试修复并续签会话。")
                fix_no_synckey()
            else:
                logging.warning("登录态可能已过期，尝试自动续签。")
            renew_session()
            time.sleep(2)

        completed = index - 1
        minutes = completed * 0.5
        logging.info("阅读脚本已完成。")
        message = (
            "微信读书自动阅读完成。\n"
            f"完成次数：{completed}/{READ_NUM}\n"
            f"阅读时长：{minutes:.1f} 分钟"
        )
        run_url = workflow_run_url()
        if run_url:
            message += f"\n运行记录：{run_url}"
        notify_result(message, is_success=True)
    except Exception as exc:
        completed = index - 1
        logging.error("阅读脚本失败：%s", exc)
        message = (
            "微信读书自动阅读失败。\n"
            f"完成次数：{completed}/{READ_NUM}\n"
            f"原因：{exc}"
        )
        run_url = workflow_run_url()
        if run_url:
            message += f"\n运行记录：{run_url}"
        notify_result(message, is_success=False)
        raise


if __name__ == "__main__":
    run()
