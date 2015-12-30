import re

from scrapy.selector import Selector
from android_apps_crawler.items import AppItem

def parse_anzhi(response):
    xpath = "//div[@class='detail_down']/a/@onclick"
    appItemList = []
    sel = Selector(response)
    for script in sel.xpath(xpath).extract():
        id = re.search(r"\d+", script).group()
        url = "http://www.anzhi.com/dl_app.php?s=%s&n=5" % (id,)
        appItem = AppItem()
        appItem['url'] = url
        appItemList.append(appItem)
    return appItemList

def parse_dcn(response):
    # xpath = "//div[@class='de-has-set clearfix']/ul/li/a/@onclick"
    print response.url
    xpath = "//a[@class='de-head-btn de-pc-btn']/@onclick"
    appItemList = []
    sel = Selector(response)

    looking_for = re.compile(r"http://android.d.cn/game/[0-9]+.html")
    if looking_for.match(response.url):
        print response
    for script in sel.xpath(xpath).extract():
        print script
        pattern = r"""\('(http[^']+)\'"""
        # example script content:
        # Adapt.downPush('http://down.androidgame-store.com/201512231053/CD97613508F7BB877E674FB06C5FE73D/new/game1/68/109068/F8E901DCD877BD7AC8B903185266E49E.apk?f=web_1',2,1043)
        url = re.search(pattern, script).group()
        appItem = AppItem()
        appItem['url'] = url
        appItemList.append(appItem)
    return appItemList
