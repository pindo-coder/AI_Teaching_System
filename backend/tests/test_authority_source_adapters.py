from datetime import date

from app.services.authority_source_adapters import get_source_adapter


def test_gov_cn_adapter_extracts_pages_content_and_metadata() -> None:
    adapter = get_source_adapter("gov.cn")
    links = adapter.parse_listing("""
        <a href="/search/zhengce/zcwjgjss/">政策搜索</a>
        <a href="/zhengce/content/202608/content_7077398.htm">最新政策正文</a>
    """, "https://www.gov.cn/zhengce/index.htm")
    parsed = adapter.parse_article("""
        <html><head>
          <meta property="og:title" content="国务院关于推进教育数字化的意见">
          <meta name="publisher" content="国务院">
          <meta name="date" content="2026-08-01">
        </head><body>
          <div class="header navigation">首页 政策 新闻</div>
          <div class="pages_content" id="UCAP-CONTENT">
            <p>为深入推进教育数字化，现提出以下具有明确政策意义的实施意见。</p>
            <p>各地区各部门应结合实际情况，完善工作机制并落实具体任务。</p>
          </div>
          <div class="related-news">相关阅读一 相关阅读二</div>
        </body></html>
    """)

    assert adapter.name == "gov-cn"
    assert links == [("https://www.gov.cn/zhengce/content/202608/content_7077398.htm", "最新政策正文")]
    assert parsed.title == "国务院关于推进教育数字化的意见"
    assert parsed.publisher == "国务院"
    assert parsed.published_date == date(2026, 8, 1)
    assert "深入推进教育数字化" in parsed.content
    assert "相关阅读" not in parsed.content
    assert parsed.parser_version == "authority-gov-cn-v1"


def test_moe_adapter_prefers_trs_editor_and_reads_visible_metadata() -> None:
    adapter = get_source_adapter("www.moe.gov.cn")
    links = adapter.parse_listing("""
        <a href="/jyb_sy/sy_wb/201301/t20130129_147290.html">微言教育</a>
        <a href="/jyb_xwfb/gzdt_gzdt/s5987/202608/t20260804_1446039.html">最新工作动态</a>
    """, "http://www.moe.gov.cn/jyb_xwfb/gzdt_gzdt/")
    parsed = adapter.parse_article("""
        <html><head><title>教育部部署高校思政课建设</title></head><body>
          <div class="header">教育部网站栏目导航</div>
          <h1>教育部部署高校思政课建设</h1>
          <div>发布时间：2026年07月31日 来源：教育部新闻办</div>
          <div class="TRS_Editor">
            <p>教育部对高校思想政治理论课建设作出新的工作部署和具体要求。</p>
            <p>通知要求各高校完善课程体系，持续提高课堂教学质量和育人实效。</p>
          </div>
          <footer>网站声明 联系我们</footer>
        </body></html>
    """)

    assert links == [("http://www.moe.gov.cn/jyb_xwfb/gzdt_gzdt/s5987/202608/t20260804_1446039.html", "最新工作动态")]
    assert parsed.title == "教育部部署高校思政课建设"
    assert parsed.publisher == "教育部新闻办"
    assert parsed.published_date == date(2026, 7, 31)
    assert "提高课堂教学质量" in parsed.content
    assert "网站声明" not in parsed.content


def test_qstheory_adapter_and_listing_prioritize_detail_links() -> None:
    adapter = get_source_adapter("qstheory.cn")
    links = adapter.parse_listing("""
        <a href="/about/index.htm">网站介绍</a>
        <a href="/20260801/299754defc9c40218349ec052d8837d0/c.html">进一步全面深化改革</a>
    """, "https://www.qstheory.cn/")
    parsed = adapter.parse_article("""
        <html><head><meta name="source" content="求是网"></head><body>
          <main class="article-content">
            <h1>进一步全面深化改革</h1>
            <p>进一步全面深化改革必须坚持党的全面领导，坚持以人民为中心。</p>
            <p>要把重大改革举措转化为推进中国式现代化的实际成效。</p>
          </main>
          <aside class="recommend">推荐文章列表</aside>
        </body></html>
    """)

    assert links[0][0] == "https://www.qstheory.cn/20260801/299754defc9c40218349ec052d8837d0/c.html"
    assert parsed.publisher == "求是网"
    assert "中国式现代化" in parsed.content
    assert "推荐文章" not in parsed.content


def test_unknown_domain_uses_generic_adapter() -> None:
    adapter = get_source_adapter("example.edu.cn")
    parsed = adapter.parse_article("""
        <html><body><article><h1>高校发布的理论材料</h1>
        <p>这是一段具有完整语义的正文材料，用于验证未知白名单来源的通用解析能力。</p>
        <p>第二段继续提供可供教学使用的完整论述和必要依据。</p></article></body></html>
    """)

    assert adapter.name == "generic"
    assert parsed.title == "高校发布的理论材料"
    assert "通用解析能力" in parsed.content


def test_editor_author_is_not_used_as_official_publisher() -> None:
    parsed = get_source_adapter("gov.cn").parse_article("""
        <html><head><meta name="author" content="网站编辑"></head><body>
        <main class="pages_content"><h1>政策文件</h1>
        <p>这是政策文件的完整正文内容，用来确认编辑姓名不会被误识别为发布机构。</p>
        <p>正文继续说明相关政策要求、适用范围和具体实施安排。</p></main></body></html>
    """)

    assert parsed.publisher == "中国政府网"
