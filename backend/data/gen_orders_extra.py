"""追加 1000 条订单：地域从上海/安庆扩展到全国 20 个大城市。

表头直接用 app.orchestration.orders_seed.COLUMNS（英文），保证与导入器零偏差。
产出两份：
  1. guoquan_orders_extra_national_1000.csv   —— 本次增量的独立文件（给已初始化的库补灌）
  2. 追加进 guoquan_orders_2025_2026_en.csv   —— 种子读的就是这份，未来全新安装一次灌全 1500 条
订单号序号从 100001 起（基础 500 条只用到 000500），不会撞号。

运行（仓库根目录）：
  PYTHONPATH=backend ../.venv_test/bin/python backend/data/gen_orders_extra.py
"""
from __future__ import annotations

import calendar
import csv
import datetime
import os
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/
from app.orchestration.orders_seed import COLUMNS  # noqa: E402

OUT = Path(__file__).resolve().parent
random.seed(20261026)

TARGET = 1000
SEQ_START = 100001

# ---------- 门店：新增 20 个大城市门店（区号用于座机） ----------
NEW_STORES = [
    ("北京", "010", "锅圈食汇(朝阳大悦城店)", "北京市朝阳区朝阳北路101号"),
    ("广州", "020", "锅圈食汇(天河体育西店)", "广州市天河区体育西路55号"),
    ("深圳", "0755", "锅圈食汇(福田彩田店)", "深圳市福田区彩田路3069号"),
    ("成都", "028", "锅圈食汇(锦江春熙店)", "成都市锦江区春熙路99号"),
    ("杭州", "0571", "锅圈食汇(西湖文三店)", "杭州市西湖区文三路478号"),
    ("武汉", "027", "锅圈食汇(江汉路店)", "武汉市江汉区江汉路206号"),
    ("南京", "025", "锅圈食汇(玄武新街口店)", "南京市玄武区中山东路300号"),
    ("西安", "029", "锅圈食汇(雁塔小寨店)", "西安市雁塔区小寨西路7号"),
    ("重庆", "023", "锅圈食汇(渝北观音桥店)", "重庆市渝北区建北一支路48号"),
    ("长沙", "0731", "锅圈食汇(芙蓉五一店)", "长沙市芙蓉区五一大道235号"),
    ("青岛", "0532", "锅圈食汇(市南香港中路店)", "青岛市市南区香港中路76号"),
    ("苏州", "0512", "锅圈食汇(姑苏观前街店)", "苏州市姑苏区观前街144号"),
    ("天津", "022", "锅圈食汇(和平滨江道店)", "天津市和平区滨江道219号"),
    ("合肥", "0551", "锅圈食汇(庐阳淮河路店)", "合肥市庐阳区淮河路266号"),
    ("昆明", "0871", "锅圈食汇(五华南屏街店)", "昆明市五华区南屏街88号"),
    ("厦门", "0592", "锅圈食汇(思明中山路店)", "厦门市思明区中山路31号"),
    ("郑州", "0371", "锅圈食汇(二七德化街店)", "郑州市二七区德化街69号"),
    ("济南", "0531", "锅圈食汇(历下泉城路店)", "济南市历下区泉城路180号"),
    ("沈阳", "024", "锅圈食汇(沈河中街店)", "沈阳市沈河区中街路212号"),
    ("哈尔滨", "0451", "锅圈食汇(道里中央大街店)", "哈尔滨市道里区中央大街134号"),
]
# 既有门店（权重低一些：老市场趋稳，增量主要来自全国扩张）
OLD_STORES = [
    ("上海", "021", "S001", "锅圈食汇(莘庄店)", "上海市闵行区莘庄镇莘建路399号"),
    ("上海", "021", "S002", "锅圈食汇(梅陇店)", "上海市闵行区梅陇镇朱行路88号"),
    ("上海", "021", "S003", "锅圈食汇(龙华店)", "上海市徐汇区龙水南路120号"),
    ("上海", "021", "S004", "锅圈食汇(塘桥店)", "上海市浦东新区浦建路560号"),
    ("上海", "021", "S005", "锅圈食汇(金桥店)", "上海市浦东新区金高路218号"),
    ("上海", "021", "S006", "锅圈食汇(彭浦店)", "上海市静安区共和新路3600号"),
    ("上海", "021", "S007", "锅圈食汇(五角场店)", "上海市杨浦区政通路105号"),
    ("上海", "021", "S008", "锅圈食汇(天山店)", "上海市长宁区天山路776号"),
    ("上海", "021", "S009", "锅圈食汇(真如店)", "上海市普陀区兰溪路342号"),
    ("上海", "021", "S010", "锅圈食汇(大场店)", "上海市宝山区沪太路4588号"),
    ("上海", "021", "S011", "锅圈食汇(南翔店)", "上海市嘉定区槎溪路660号"),
    ("上海", "021", "S012", "锅圈食汇(九亭店)", "上海市松江区沪亭北路199号"),
    ("安庆", "0556", "S013", "锅圈食汇(华中路店)", "安庆市迎江区华中路315号"),
    ("安庆", "0556", "S014", "锅圈食汇(宿松人民路店)", "安庆市宿松县孚玉镇人民路286号"),
]

business_hours = ["09:00-21:30", "09:00-22:00", "09:30-21:30", "09:30-22:00", "10:00-21:00"]


def gen_landline(code: str) -> str:
    return f"{code}-" + str(random.randint(5, 8)) + "".join(str(random.randint(0, 9)) for _ in range(7))


def build_store(seq: int, city: str, code: str, sid: str, name: str, addr: str) -> dict:
    return {"id": sid, "name": name, "addr": addr, "city": city,
            "hours": random.choice(business_hours), "phone": gen_landline(code)}


stores = [build_store(i, c, k, f"S1{i:02d}", n, a) for i, (c, k, n, a) in enumerate(NEW_STORES, 1)]
stores += [build_store(100 + i, c, k, sid, n, a) for i, (c, k, sid, n, a) in enumerate(OLD_STORES, 1)]
# 权重：新城市门店 1.2，既有门店 0.6 → 增量约 7 成落在新增城市
store_weights = [1.2 if s["id"].startswith("S1") else 0.6 for s in stores]

# ---------- 收货地址池：按城市 ----------
CITY_ADDR = {
    "北京市": (["朝阳区", "海淀区", "丰台区"], ["建国路", "中关村大街", "丰台北路"]),
    "广州市": (["天河区", "越秀区", "海珠区"], ["体育西路", "中山五路", "江南大道"]),
    "深圳市": (["福田区", "南山区", "罗湖区"], ["彩田路", "科技南路", "人民南路"]),
    "成都市": (["锦江区", "武侯区", "青羊区"], ["春熙路", "人民南路", "光华村街"]),
    "杭州市": (["西湖区", "拱墅区", "滨江区"], ["文三路", "湖墅南路", "江南大道"]),
    "武汉市": (["江汉区", "武昌区", "洪山区"], ["江汉路", "中南路", "珞狮路"]),
    "南京市": (["玄武区", "鼓楼区", "秦淮区"], ["中山东路", "湖南路", "升州路"]),
    "西安市": (["雁塔区", "碑林区", "未央区"], ["小寨西路", "南二环", "凤城二路"]),
    "重庆市": (["渝北区", "江北区", "南岸区"], ["建北一支路", "洋河一路", "南城大道"]),
    "长沙市": (["芙蓉区", "天心区", "岳麓区"], ["五一大道", "黄兴路", "麓山南路"]),
    "青岛市": (["市南区", "市北区", "崂山区"], ["香港中路", "台东三路", "海尔路"]),
    "苏州市": (["姑苏区", "工业园区", "吴中区"], ["观前街", "星海街", "东吴北路"]),
    "天津市": (["和平区", "河西区", "南开区"], ["滨江道", "友谊路", "鞍山西道"]),
    "合肥市": (["庐阳区", "蜀山区", "包河区"], ["淮河路", "长江西路", "马鞍山路"]),
    "昆明市": (["五华区", "盘龙区", "西山区"], ["南屏街", "北京路", "滇池路"]),
    "厦门市": (["思明区", "湖里区"], ["中山路", "嘉禾路", "吕岭路"]),
    "郑州市": (["二七区", "金水区", "中原区"], ["德化街", "花园路", "中原路"]),
    "济南市": (["历下区", "市中区", "天桥区"], ["泉城路", "泺源大街", "北园大街"]),
    "沈阳市": (["沈河区", "和平区", "铁西区"], ["中街路", "南京北街", "兴华街"]),
    "哈尔滨市": (["道里区", "南岗区", "道外区"], ["中央大街", "学府路", "靖宇街"]),
    "上海市": (["闵行区", "徐汇区", "浦东新区", "静安区", "长宁区", "普陀区", "杨浦区", "宝山区", "嘉定区", "松江区"],
               ["莘建路", "龙水南路", "浦建路", "共和新路", "政通路", "天山路", "兰溪路", "沪太路", "莲花南路", "东川路"]),
    "安庆市": (["迎江区", "宿松县"], ["华中路", "人民路"]),
}


def gen_addr(city: str) -> str:
    districts, roads = CITY_ADDR.get(city) or CITY_ADDR[city + "市"]
    d, r = random.choice(districts), random.choice(roads)
    if random.random() < 0.7:
        nong, lou, room = random.randint(1, 99), random.randint(1, 40), random.randint(101, 3004)
        return f"{city}{d}{r}{nong}弄{lou}号{room}室"
    return f"{city}{d}{r}{random.randint(1, 500)}号"


addr_id_map: dict[str, str] = {}
addr_seq = 0


def get_addr_id(addr: str) -> str:
    global addr_seq
    if addr not in addr_id_map:
        addr_seq += 1
        addr_id_map[addr] = "A%08d" % (200000 + addr_seq)  # 与基础数据的地址段区分
    return addr_id_map[addr]


# ---------- 商品 / 用户 / 券 / 活动（沿用基础数据的口径） ----------
product_defs = [
    ("精品毛肚", "单品", 39.9), ("鲜切羊肉卷", "单品", 49.9), ("澳洲肥牛卷", "单品", 55.9),
    ("手打虾滑", "单品", 29.9), ("潮汕牛肉丸", "单品", 25.9), ("墨鱼丸", "单品", 19.9),
    ("鱼籽福袋", "单品", 22.9), ("鲜鸭血", "单品", 8.9), ("冻豆腐", "单品", 6.9),
    ("豆皮结", "单品", 7.9), ("菌菇拼盘", "单品", 15.9), ("娃娃菜", "单品", 9.9),
    ("土豆片", "单品", 6.9), ("火锅宽粉", "单品", 8.9), ("红糖糍粑", "单品", 12.9),
    ("小酥肉", "单品", 19.9), ("无骨鸡爪", "单品", 26.9), ("火山石烤肠", "单品", 16.9),
    ("羊肉串(10串)", "单品", 29.9), ("秘制鸡翅中", "单品", 21.9), ("掌中宝", "单品", 23.9),
    ("鲜鸭肠", "单品", 18.9), ("牛黄喉", "单品", 32.9), ("牛百叶", "单品", 27.9),
    ("梅林午餐肉", "单品", 13.9), ("蟹肉棒", "单品", 15.9), ("手工蛋饺", "单品", 17.9),
    ("水晶虾饺", "单品", 16.9), ("牛油麻辣火锅底料", "单品", 15.9), ("番茄火锅底料", "单品", 12.9),
    ("菌汤火锅底料", "单品", 12.9), ("芝麻酱蘸料", "单品", 9.9), ("蒜蓉油碟", "单品", 6.9),
    ("老北京酸梅汤(1L)", "单品", 9.9), ("可乐(1.25L)", "单品", 6.9), ("苏打气泡水(6瓶)", "单品", 12.9),
    ("低温酸奶(4杯)", "单品", 9.9),
    ("双人火锅套餐", "套餐", 88.0), ("家庭欢聚火锅套餐(4-6人)", "套餐", 199.0),
    ("精品毛肚套餐", "套餐", 59.9), ("烧烤套餐(家庭版)", "套餐", 129.0), ("羊肉串套餐", "套餐", 69.9),
    ("羊蝎子火锅套餐(冬季)", "套餐", 158.0), ("佛跳墙预制菜礼盒", "套餐", 299.0),
    ("小龙虾尾套餐(夏季)", "套餐", 89.0), ("酸菜鱼套餐", "套餐", 69.9), ("鸳鸯锅底套餐", "套餐", 39.9),
    ("单人自热小火锅套餐", "套餐", 29.9), ("冬至水饺套餐", "套餐", 49.9), ("儿童成长套餐", "套餐", 45.9),
]
products = [{"name": n, "type": t, "price": p, "cents": int(round(p * 100))} for n, t, p in product_defs]
products_by_name = {p["name"]: p for p in products}
freebie_pool = ["手打虾滑", "精品毛肚", "鲜鸭血", "小酥肉", "鱼籽福袋", "红糖糍粑", "无骨鸡爪", "手工蛋饺", "羊肉串(10串)"]

male_names = ["张伟", "李强", "王磊", "刘洋", "陈军", "杨帆", "赵鹏", "黄志强", "周杰", "吴刚", "徐明", "孙浩", "马超",
              "朱毅", "胡斌", "郭涛", "林峰", "何宇", "高翔", "罗成", "郑凯", "梁栋", "谢辉", "宋平", "唐昊", "韩磊",
              "冯军", "曹阳", "彭飞", "董斌", "潘伟", "袁浩", "蔡勇", "蒋鑫", "余亮", "杜海", "叶鹏", "程刚", "苏强", "魏东"]
female_names = ["王芳", "李娜", "张静", "刘敏", "陈雪", "杨慧", "赵倩", "黄丽", "周婷", "吴琼", "徐燕", "孙悦", "马莉",
                "朱琳", "胡静", "郭雪", "林晓", "何露", "高媛", "罗丹", "郑雯", "梁爽", "谢楠", "宋佳", "唐丽", "韩雪",
                "冯婷", "曹颖", "彭丽", "董悦", "潘婷", "袁梦", "蔡文静", "蒋莉", "余欢", "杜娟", "叶敏", "程雪", "苏婉", "魏雪"]
nicknames = ["火锅爱好者", "麻辣一姐", "干饭人", "毛肚大户", "虾滑控", "火锅配冰阔落", "无辣不欢", "夜宵小分队", "干饭魂",
             "吃货本货", "阿汤哥", "冒菜不加辣", "烧烤大师", "居家小厨神", "辣妹不辣", "火锅侠", "丸子开会", "汤底杀手",
             "深夜食堂常客", "快乐肥宅水", "觅食小分队", "暖锅先生", "芝麻酱狂魔", "香菜爱好者", "不辣不舒服斯基",
             "涮肉第一名", "锅底三拼", "灶台边的人", "干饭王中王", "七天吃四顿", "火锅自由人", "周末火锅局",
             "我的锅我做主", "涮火锅ing", "吃货集结号", "锅圈小粉丝", "小锅锅", "咕噜咕噜", "呷哺呷哺", "热气腾腾"]
levels = [("普通会员", 0, 500), ("银卡会员", 500, 3000), ("金卡会员", 3000, 8000), ("黑金会员", 8000, 20000)]
level_weights = [0.45, 0.30, 0.18, 0.07]


def gen_mobile() -> str:
    pre = random.choice(["135", "136", "137", "138", "139", "150", "151", "152", "158", "159",
                         "173", "176", "177", "178", "185", "186", "187", "188", "189", "191", "198", "199"])
    return pre + "".join(str(random.randint(0, 9)) for _ in range(8))


users = []
for i in range(160):
    gender = "男" if random.random() < 0.48 else "女"
    name = random.choice(male_names if gender == "男" else female_names)
    lv, lo, hi = random.choices(levels, weights=level_weights, k=1)[0]
    users.append({"id": "U%08d" % (20000001 + i), "nick": random.choice(nicknames), "name": name,
                  "gender": gender, "level": lv, "points": random.randint(lo, hi), "phone": gen_mobile()})

coupon_templates = {
    "满减": [(100, 20), (150, 30), (200, 45), (300, 70)],
    "满折": [(88, 0.95, "9.5"), (128, 0.90, "9"), (199, 0.85, "8.5")],
    "固定": [(0, 3), (0, 5), (20, 10)],
}
pt_names = ["全国扩张开业季-火锅拼团", "城市新店开业-爆品拼团", "会员日拼团-毛肚专场", "周末爆品拼团", "新品尝鲜拼团-烧烤季"]
jl_names = ["门店社区接龙-牛肉专场", "接龙-丸子狂欢周", "接龙-冬季囤货专场", "接龙-全国开业囤货", "接龙-周末囤货专场"]
remarks_pool = ["", "", "", "", "不要辣", "微辣就行", "多放蒜蓉", "汤底帮忙打包", "尽快配送", "放门口即可，电话联系",
                "到店自提，报手机尾号", "多加冰", "6点后再配送", "孩子吃，不要加辣", "芝麻酱多来一份",
                "工作日午间配送", "少放花椒", "锅底要鸳鸯的", ""]
status_pool = [("已完成", 0.74), ("配送中", 0.07), ("已支付", 0.06), ("待支付", 0.04), ("已取消", 0.05), ("已退款", 0.04)]
channels = [("微信小程序", 0.50), ("抖音小程序", 0.08), ("门店扫码", 0.17), ("美团外卖", 0.15), ("饿了么外卖", 0.10)]
order_types = [("普通订单", 0.72), ("拼团订单", 0.16), ("接龙订单", 0.12)]
hour_w = {9: 1, 10: 2, 11: 4, 12: 3, 13: 2, 14: 1, 15: 1, 16: 2, 17: 5, 18: 9, 19: 9, 20: 8, 21: 5, 22: 1}


def choose_fulfillment(channel: str, otype: str) -> str:
    if otype == "接龙订单":
        return "门店自提" if random.random() < 0.85 else "同城配送"
    if otype == "拼团订单":
        return "同城配送" if random.random() < 0.6 else "门店自提"
    if channel in ("美团外卖", "饿了么外卖"):
        return "平台外卖配送"
    if channel == "门店扫码":
        return "门店自提"
    return "同城配送" if random.random() < 0.7 else "门店自提"


def build_items(month: int):
    winter, summer = month in (11, 12, 1, 2), month in (6, 7, 8)
    n_items = random.choices([1, 2, 3, 4, 5, 6, 7, 8], weights=[0.08, 0.18, 0.26, 0.22, 0.13, 0.07, 0.04, 0.02], k=1)[0]
    chosen, names = [], set()

    def add(p):
        if p["name"] in names:
            return
        names.add(p["name"])
        chosen.append((p, 1 if p["type"] == "套餐" else random.randint(1, 3)))

    for _ in range(n_items):
        add(random.choice(products))
    if winter and random.random() < 0.18:
        add(random.choice([products_by_name["羊蝎子火锅套餐(冬季)"], products_by_name["佛跳墙预制菜礼盒"], products_by_name["冬至水饺套餐"]]))
    if summer and random.random() < 0.18:
        add(products_by_name["小龙虾尾套餐(夏季)"])
    return chosen


def make_coupon(goods_cents: int, items):
    t = random.random()
    names_in_cart = {p["name"] for p, _ in items}
    if t < 0.40:
        elig = [(thr, val) for thr, val in coupon_templates["满减"] if goods_cents >= thr * 100]
        if not elig:
            return None, None, 0
        thr, val = random.choice(elig)
        return {"ctype": "满减券", "cname": f"满{thr}减{val}", "cval": float(val)}, None, val * 100
    if t < 0.60:
        elig = [(thr, rate, disp) for thr, rate, disp in coupon_templates["满折"] if goods_cents >= thr * 100]
        if not elig:
            return None, None, 0
        thr, rate, disp = random.choice(elig)
        return {"ctype": "满折券", "cname": f"满{thr}享{disp}折", "cval": float(rate)}, None, int(round(goods_cents * (1 - rate)))
    if t < 0.80:
        elig = [(thr, val) for thr, val in coupon_templates["固定"] if goods_cents >= thr * 100]
        if not elig:
            return None, None, 0
        thr, val = random.choice(elig)
        cname = f"{val}元无门槛券" if thr == 0 else f"满{thr}减{val}券"
        return {"ctype": "固定金额券", "cname": cname, "cval": float(val)}, None, val * 100
    cands = [p for p in freebie_pool if p not in names_in_cart]
    if not cands:
        return None, None, 0
    p = products_by_name[random.choice(cands)]
    return {"ctype": "0元购券", "cname": f"0元购-{p['name']} 1份", "cval": float(p["price"])}, (p, 1), p["cents"]


def pick_day(y: int, m: int, last_cap: int) -> int:
    last = min(calendar.monthrange(y, m)[1], last_cap)
    days = list(range(1, last + 1))
    ws = [1.5 if datetime.date(y, m, d).weekday() >= 5 else 1.0 for d in days]
    return random.choices(days, weights=ws, k=1)[0]


# ---------- 生成 ----------
periods = [(2026, 9, 1.0), (2026, 10, 1.5)]
total_w = sum(w for _, _, w in periods)
counts = {}
acc = 0
for i, (y, m, w) in enumerate(periods):
    n = TARGET * w / total_w if i < len(periods) - 1 else TARGET - acc
    counts[(y, m)] = int(n)
    acc += int(n)

coupon_codes_used: set[str] = set()
rows: list[dict] = []
order_seq = SEQ_START
LAST_DAY = {"2026-09": 30, "2026-10": 25}

for (y, m), n in counts.items():
    for _ in range(n):
        order_seq += 1
        status = random.choices([s for s, _ in status_pool], weights=[w for _, w in status_pool], k=1)[0]
        channel = random.choices([c for c, _ in channels], weights=[w for _, w in channels], k=1)[0]
        otype = random.choices([t for t, _ in order_types], weights=[w for _, w in order_types], k=1)[0]
        store = random.choices(stores, weights=store_weights, k=1)[0]
        fulfillment = choose_fulfillment(channel, otype)

        hour = random.choices(list(hour_w), weights=list(hour_w.values()), k=1)[0]
        create = datetime.datetime(y, m, pick_day(y, m, LAST_DAY[f"{y}-{m:02d}"]), hour,
                                   random.randint(0, 59), random.randint(0, 59))

        items = build_items(m)
        goods_cents = sum(p["cents"] * q for p, q in items)
        delivery_cents = 600 if (fulfillment != "门店自提" and goods_cents < 5900) else 0
        packing_cents = 100 if fulfillment != "门店自提" else 0
        total_cents = goods_cents + delivery_cents + packing_cents

        paid = status in ("已完成", "配送中", "已支付", "已退款")
        coupon, extra_item, discount_cents = None, None, 0
        if paid and random.random() < 0.45:
            coupon, extra_item, discount_cents = make_coupon(goods_cents, items)
            if extra_item:
                items.append(extra_item)
                goods_cents = sum(p["cents"] * q for p, q in items)
                delivery_cents = 600 if (fulfillment != "门店自提" and goods_cents < 5900) else 0
                packing_cents = 100 if fulfillment != "门店自提" else 0
                total_cents = goods_cents + delivery_cents + packing_cents
                discount_cents = min(discount_cents, total_cents)

        pay_cents = total_cents - discount_cents if paid else 0
        order_no = "GQ%s%06d" % (create.strftime("%Y%m%d"), order_seq)
        goods_text = "；".join(f"{p['name']}（{p['type']}）x{q}" for p, q in items)

        pay_time = complete_time = ""
        refund_amount, points = 0.0, 0
        if paid:
            pay_time = (create + datetime.timedelta(minutes=random.randint(1, 10), seconds=random.randint(0, 59))).strftime("%Y-%m-%d %H:%M:%S")
            if status == "已退款":
                refund_amount = pay_cents / 100
                complete_time = (create + datetime.timedelta(minutes=random.randint(40, 300))).strftime("%Y-%m-%d %H:%M:%S")
            elif status == "已完成":
                span = random.randint(40, 150) if fulfillment == "门店自提" else random.randint(90, 360)
                complete_time = (create + datetime.timedelta(minutes=span)).strftime("%Y-%m-%d %H:%M:%S")
            points = 0 if status == "已退款" else int(pay_cents // 100)

        coupon_code = coupon_name = coupon_type = coupon_value = ""
        if coupon:
            coupon_type, coupon_name, coupon_value = coupon["ctype"], coupon["cname"], coupon["cval"]
            while True:
                cc = "GQ%s%04d" % (create.strftime("%Y%m%d"), random.randint(0, 9999))
                if cc not in coupon_codes_used:
                    coupon_codes_used.add(cc)
                    coupon_code = cc
                    break

        user = random.choice(users)
        receiver_name = receiver_phone = address = address_id = ""
        if fulfillment != "门店自提":
            receiver_name, receiver_phone = user["name"], user["phone"]
            address = gen_addr(store["city"])
            address_id = get_addr_id(address)

        rows.append({
            "order_no": order_no,
            "order_create_time": create.strftime("%Y-%m-%d %H:%M:%S"),
            "pay_time": pay_time,
            "order_status": status,
            "order_type": otype,
            "order_channel": channel,
            "activity_id": ("PT%s%03d" % (create.strftime("%Y%m%d"), random.randint(0, 999))) if otype == "拼团订单"
            else (("JL%s%03d" % (create.strftime("%Y%m%d"), random.randint(0, 999))) if otype == "接龙订单" else ""),
            "activity_name": random.choice(pt_names) if otype == "拼团订单" else (random.choice(jl_names) if otype == "接龙订单" else ""),
            "store_id": store["id"],
            "store_name": store["name"],
            "store_address": store["addr"],
            "store_business_hours": store["hours"],
            "store_phone": store["phone"],
            "fulfillment_type": fulfillment,
            "goods_list": goods_text,
            "goods_quantity": sum(q for _, q in items),
            "goods_amount": "%.2f" % (goods_cents / 100),
            "delivery_fee": "%.2f" % (delivery_cents / 100),
            "packing_fee": "%.2f" % (packing_cents / 100),
            "total_amount": "%.2f" % (total_cents / 100),
            "discount_amount": "%.2f" % (discount_cents / 100),
            "pay_amount": "%.2f" % (pay_cents / 100),
            "points_earned": points,
            "is_coupon_used": "是" if coupon else "否",
            "coupon_code": coupon_code,
            "coupon_type": coupon_type,
            "coupon_name": coupon_name,
            "coupon_value": coupon_value,
            "receiver_name": receiver_name,
            "receiver_phone": receiver_phone,
            "address_id": address_id,
            "address": address,
            "order_remark": random.choice(remarks_pool),
            "order_complete_time": complete_time,
            "refund_amount": "%.2f" % refund_amount,
            "user_id": user["id"],
            "user_nickname": user["nick"],
            "user_name": user["name"],
            "user_gender": user["gender"],
            "member_level": user["level"],
            "member_points": user["points"],
            "user_phone": user["phone"],
            "need_invoice": "是" if random.random() < 0.12 else "否",
        })

rows.sort(key=lambda r: (r["order_create_time"], r["order_no"]))

extra_path = OUT / "guoquan_orders_extra_national_1000.csv"
with extra_path.open("w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)
print("增量文件:", extra_path.name, len(rows), "行")

# 追加进种子主文件（未来全新安装一次灌全），按主文件现有表头写
base_path = OUT / "guoquan_orders_2025_2026_en.csv"
with base_path.open(encoding="utf-8-sig", newline="") as f:
    reader = csv.DictReader(f)
    base_header = reader.fieldnames
    base_rows = list(reader)
existing_nos = {r["order_no"] for r in base_rows if "order_no" in r}
added = [r for r in rows if r["order_no"] not in existing_nos]
with base_path.open("a", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=base_header, extrasaction="ignore")
    w.writerows(added)
print(f"种子主文件追加 {len(added)} 行（现共 {len(base_rows) + len(added)} 条）")

# ---------- 摘要 ----------
print("城市分布(按门店):", dict(Counter(r["store_name"] for r in rows).most_common(8)), "...")
new_city_orders = sum(1 for r in rows if r["store_id"].startswith("S1"))
print(f"新增城市订单占比: {new_city_orders}/{len(rows)} = {new_city_orders / len(rows):.0%}")
print("状态分布:", dict(Counter(r["order_status"] for r in rows)))
print("月份分布:", dict(Counter(r["order_create_time"][:7] for r in rows)))
