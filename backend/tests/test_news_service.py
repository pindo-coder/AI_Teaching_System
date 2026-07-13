from app.services.news_service import _parse_feed


def test_parse_feed_supports_gb_encoded_rss() -> None:
    xml = '<?xml version="1.0" encoding="gb2312"?><rss><channel><item><title>测试时政</title></item></channel></rss>'
    root = _parse_feed(xml.encode("gb18030"))
    assert root.findtext(".//item/title") == "测试时政"
