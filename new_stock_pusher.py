import os
import time
import logging
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 环境变量（在Render中配置）
WECHAT_WEBHOOK = os.getenv('WECHAT_WEBHOOK', '')
TEST_MODE = os.getenv('TEST_MODE', 'False').lower() == 'true'

# 存储状态（使用文件，适合Render的持久化存储）
STATUS_FILE = 'pushed_status.json'

class NewStockPusher:
    def __init__(self):
        self.trading_hours = {
            'morning': (9, 30, 11, 30),
            'afternoon': (13, 0, 15, 0)
        }

    def is_trading_day(self):
        """判断是否为交易日（简单判断：非周末，后续可扩展）"""
        if TEST_MODE:
            return True  # 测试模式始终视为交易日
        
        weekday = datetime.now().weekday()
        return weekday < 5  # 周一到周五

    def is_in_trading_hours(self):
        """判断是否在交易时间段内"""
        if TEST_MODE:
            return True  # 测试模式始终视为交易时间
        
        now = datetime.now()
        h, m = now.hour, now.minute
        
        # 上午时段
        m_start_h, m_start_m, m_end_h, m_end_m = self.trading_hours['morning']
        in_morning = (h > m_start_h or (h == m_start_h and m >= m_start_m)) and \
                    (h < m_end_h or (h == m_end_h and m <= m_end_m))
        
        # 下午时段
        a_start_h, a_start_m, a_end_h, a_end_m = self.trading_hours['afternoon']
        in_afternoon = (h > a_start_h or (h == a_start_h and m >= a_start_m)) and \
                      (h < a_end_h or (h == a_end_h and m <= a_end_m))
        
        return in_morning or in_afternoon

    def has_pushed_today(self):
        """检查今天是否已成功推送"""
        try:
            with open(STATUS_FILE, 'r') as f:
                data = f.read().strip()
                if not data:
                    return False
                status = eval(data)  # 简单解析
                last_date = status.get('last_pushed_date', '')
                return last_date == datetime.now().strftime('%Y-%m-%d')
        except:
            return False

    def update_push_status(self):
        """更新推送状态"""
        with open(STATUS_FILE, 'w') as f:
            f.write(str({
                'last_pushed_date': datetime.now().strftime('%Y-%m-%d'),
                'last_pushed_time': datetime.now().strftime('%H:%M:%S')
            }))

    def crawl_new_stocks(self):
        """从无需API的数据源爬取新股信息（示例网站，实际可替换）"""
        try:
            url = 'https://www.iwencai.com/unifiedwap/result?w=今日新股&querytype=stock'
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            response = requests.get(url, headers=headers, timeout=10)
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 解析新股数据（根据实际网页结构调整）
            stocks = []
            # 示例：假设网页中有class为"stock-item"的元素
            for item in soup.select('.stock-item')[:5]:  # 取前5只
                name = item.select_one('.stock-name').text.strip() if item.select_one('.stock-name') else '未知'
                code = item.select_one('.stock-code').text.strip() if item.select_one('.stock-code') else '未知'
                price = item.select_one('.stock-price').text.strip() if item.select_one('.stock-price') else '未知'
                stocks.append(f"{name}（{code}）- 发行价：{price}")
            
            return stocks if stocks else ["今日无新股信息"]
        except Exception as e:
            logging.error(f"爬取失败：{str(e)}")
            return None

    def send_wechat_message(self, content):
        """通过企业微信机器人发送消息"""
        if not WECHAT_WEBHOOK:
            logging.error("未配置企业微信Webhook，无法发送消息")
            return False
        
        try:
            data = {
                "msgtype": "text",
                "text": {
                    "content": f"📈 今日新股认购信息\n{content}\n\n发送时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                }
            }
            
            response = requests.post(
                WECHAT_WEBHOOK,
                headers={'Content-Type': 'application/json'},
                json=data,
                timeout=10
            )
            
            if response.json().get('errcode') == 0:
                logging.info("消息发送成功")
                return True
            else:
                logging.error(f"消息发送失败：{response.text}")
                return False
        except Exception as e:
            logging.error(f"发送消息出错：{str(e)}")
            return False

    def run(self):
        """主运行逻辑"""
        logging.info("程序启动，开始监控新股信息...")
        
        while True:
            today = datetime.now().strftime('%Y-%m-%d')
            logging.info(f"当前日期：{today}，测试模式：{'开启' if TEST_MODE else '关闭'}")
            
            # 检查是否为交易日
            if not self.is_trading_day():
                logging.info("非交易日，等待至下一个交易日...")
                # 非交易日每6小时检查一次
                time.sleep(6 * 3600)
                continue
            
            # 检查是否已推送
            if self.has_pushed_today():
                logging.info("今日已成功推送，等待至次日...")
                # 等待至次日9点前
                next_day = datetime.now() + timedelta(days=1)
                next_check = next_day.replace(hour=8, minute=0, second=0, microsecond=0)
                sleep_seconds = (next_check - datetime.now()).total_seconds()
                time.sleep(max(0, sleep_seconds))
                continue
            
            # 检查是否在交易时间内
            if not self.is_in_trading_hours():
                logging.info("当前不在交易时间内，等待至交易开始...")
                # 计算距离下一个交易时段的时间
                now = datetime.now()
                m_start = now.replace(
                    hour=self.trading_hours['morning'][0],
                    minute=self.trading_hours['morning'][1],
                    second=0, microsecond=0
                )
                a_start = now.replace(
                    hour=self.trading_hours['afternoon'][0],
                    minute=self.trading_hours['afternoon'][1],
                    second=0, microsecond=0
                )
                
                if now < m_start:
                    sleep_seconds = (m_start - now).total_seconds()
                else:
                    sleep_seconds = (a_start - now).total_seconds() if now < a_start else 3600
                
                time.sleep(max(0, sleep_seconds))
                continue
            
            # 爬取新股数据
            stocks = self.crawl_new_stocks()
            if not stocks:
                logging.warning("未获取到新股数据，将重试...")
                time.sleep(30 * 60)  # 30分钟后重试
                continue
            
            # 发送消息
            content = '\n'.join([f"{i+1}. {stock}" for i, stock in enumerate(stocks)])
            success = self.send_wechat_message(content)
            
            if success:
                self.update_push_status()
                logging.info("推送成功，等待至次日...")
                # 成功后等待至次日
                next_day = datetime.now() + timedelta(days=1)
                next_check = next_day.replace(hour=8, minute=0, second=0, microsecond=0)
                time.sleep(max(0, (next_check - datetime.now()).total_seconds()))
            else:
                logging.warning("推送失败，30分钟后重试...")
                time.sleep(30 * 60)  # 30分钟后重试

if __name__ == "__main__":
    # 支持清除状态（测试用）
    if len(os.argv) > 1 and os.argv[1] == 'clear':
        if os.path.exists(STATUS_FILE):
            os.remove(STATUS_FILE)
            print("已清除推送状态")
        sys.exit(0)
    
    pusher = NewStockPusher()
    pusher.run()
