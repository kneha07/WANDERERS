"""Make the Traditional Chinese dictionaries from the Simplified ones with OpenCC.

  artifacts/i18n/zh-N.json --s2twp--> tw-N.json  (Taiwan: 軟體, 影片, 網路, 裡)
                           --s2hk---> hk-N.json  (Hong Kong: 軟件, 網絡, 裏), then HK_WORDS

Only the translations are converted; the English keys and {n} placeholders stay the same.
Run after any change to zh-*.json, then run scripts/build_i18n.py.
Needs: pip install opencc-python-reimplemented==0.1.7 (build-time only; the site does not use it).
"""
import json
from pathlib import Path

from opencc import OpenCC

# s2hk changes characters only, so mainland words stay (視頻, 搜索, 屏幕). These are the Hong Kong words for the
# mainland words found in our text. Longest first. Words that Hong Kong shares with the mainland stay
# (軟件, 網絡, 數據, 像素, 項目, 算法). 質量 also means "mass", so only the "quality" phrases change.
HK_WORDS = {
    "筆記本電腦": "手提電腦", "數據質量": "數據質素", "質量檢查": "質素檢查", "質量篩選": "質素篩選", "質量差": "質素差",
    "新標籤頁": "新分頁", "高級用户": "進階用户", "數據文件": "數據檔案", "它的文件": "它的檔案", "傳感器": "感應器",
    "交互式": "互動式", "剪貼板": "剪貼簿", "分辨率": "解像度",
    "視頻": "影片", "搜索": "搜尋", "保存": "儲存", "加載": "載入", "屏幕": "螢幕", "全屏": "全螢幕", "實時": "即時",
    "默認": "預設", "鼠標": "滑鼠", "菜單": "選單", "鏈接": "連結", "導出": "匯出", "信息": "資訊", "設備": "裝置",
    "交互": "互動", "創建": "建立", "刷新": "重新載入", "程序": "程式", "硅": "矽",
}


def hk_words(text):
    for a, b in HK_WORDS.items():  # dict keeps the order above: longer phrases first
        text = text.replace(a, b)
    return text


def main():
    src = Path(__file__).resolve().parent.parent / "artifacts" / "i18n"
    for code, cfg in (("tw", "s2twp"), ("hk", "s2hk")):
        cc = OpenCC(cfg)
        fix = hk_words if code == "hk" else (lambda t: t)
        for f in sorted(src.glob("zh-*.json")):
            d = json.loads(f.read_text(encoding="utf-8"))
            out = src / f.name.replace("zh-", f"{code}-", 1)
            out.write_text(json.dumps({k: fix(cc.convert(v)) for k, v in d.items()}, ensure_ascii=False, indent=0) + "\n",
                           encoding="utf-8", newline="\n")
        print(code, cfg, "done")


if __name__ == "__main__":
    # Self-check: Hong Kong words replace mainland ones; 質量 as "mass" stays.
    t = hk_words(OpenCC("s2hk").convert("观看视频 搜索 保存 正在加载 屏幕 数据质量 木星质量 软件 网络 程序 新标签页"))
    assert t == "觀看影片 搜尋 儲存 正在載入 螢幕 數據質素 木星質量 軟件 網絡 程式 新分頁", t
    main()
