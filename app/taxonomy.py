# Source codes are ingestion details. Client-facing IDs are stable semantic names.
TYPES = [
    ('kanji_reading', 'vocabulary', '汉字读音', '漢字読み'),
    ('orthography', 'vocabulary', '汉字表记', '表記'),
    ('word_formation', 'vocabulary', '词语构成', '語形成'),
    ('context_vocabulary', 'vocabulary', '语境选词', '文脈規定'),
    ('paraphrase', 'vocabulary', '近义替换', '言い換え類義'),
    ('word_usage', 'vocabulary', '词语用法', '用法'),
    ('grammar_choice', 'grammar', '语法选择', '文の文法'),
    ('sentence_order', 'grammar', '句子排序', '文の組み立て'),
    ('text_grammar', 'grammar', '文章语法', '文章の文法'),
    ('short_reading', 'reading', '短篇理解', '内容理解（短文）'),
    ('medium_reading', 'reading', '中篇理解', '内容理解（中文）'),
    ('long_reading', 'reading', '长篇理解', '内容理解（長文）'),
    ('integrated_reading', 'reading', '综合理解', '統合理解'),
    ('argument_reading', 'reading', '主张理解', '主張理解'),
    ('information_search', 'reading', '信息检索', '情報検索'),
    ('listening_task', 'listening', '课题理解', '課題理解'),
    ('listening_points', 'listening', '要点理解', 'ポイント理解'),
    ('listening_overview', 'listening', '概要理解', '概要理解'),
    ('listening_expression', 'listening', '表达选择', '発話表現'),
    ('listening_response', 'listening', '即时应答', '即時応答'),
    ('listening_integrated', 'listening', '综合理解', '統合理解'),
]
CODES = dict(zip([11,12,13,14,15,16,21,22,23,31,32,33,34,35,36,41,42,43,44,45,46],
                 [row[0] for row in TYPES]))


def type_id(level, code):
    # N3's historical source codes 13 and 14 both describe contextual vocabulary.
    if level == 'N3' and code in {13, 14}:
        return 'context_vocabulary'
    return CODES.get(code)
