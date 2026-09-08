/**
 * 研经日课数据全量审计脚本
 * 检查项：章节覆盖 vs 圣经标准、繁简残留、错字、排版问题、数据结构
 */
import { readFileSync } from 'fs'
import { fileURLToPath } from 'url'
import { dirname, join } from 'path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const dataDir = join(__dirname, '..', 'frontend', 'src', 'data')

const nt = JSON.parse(readFileSync(join(dataDir, 'study_articles.json'), 'utf8'))
const ot = JSON.parse(readFileSync(join(dataDir, 'ot_articles.json'), 'utf8'))
const all = [...ot.map(a => ({ ...a, _t: 'ot' })), ...nt.map(a => ({ ...a, _t: 'nt' }))]

// ========== 圣经标准章节数 ==========
const STD_CHAPTERS = {
  ot: {
    '创世记': 50, '出埃及记': 40, '利未记': 27, '民数记': 36, '申命记': 34,
    '约书亚记': 24, '士师记': 21, '路得记': 4,
    '撒母耳记上': 31, '撒母耳记下': 24, '列王纪上': 22, '列王纪下': 25,
    '历代志上': 29, '历代志下': 36, '以斯拉记': 10, '尼希米记': 13, '以斯帖记': 10,
    '约伯记': 42, '诗篇': 150, '箴言': 31, '传道书': 12, '雅歌': 8,
    '以赛亚书': 66, '耶利米书': 52, '耶利米哀歌': 5, '以西结书': 48, '但以理书': 12,
    '何西阿书': 14, '约珥书': 3, '阿摩司书': 9, '俄巴底亚书': 1, '约拿书': 4,
    '弥迦书': 7, '那鸿书': 3, '哈巴谷书': 3, '西番雅书': 3, '哈该书': 2,
    '撒迦利亚书': 14, '玛拉基书': 4,
  },
  nt: {
    '马太福音': 28, '马可福音': 16, '路加福音': 24, '约翰福音': 21,
    '使徒行传': 28,
    '罗马书': 16, '哥林多前书': 16, '哥林多后书': 13, '加拉太书': 6,
    '以弗所书': 6, '腓立比书': 4, '歌罗西书': 4, '帖撒罗尼迦前书': 5,
    '帖撒罗尼迦后书': 3, '提摩太前书': 6, '提摩太后书': 4, '提多书': 3,
    '腓利门书': 1, '希伯来书': 13, '雅各书': 5, '彼得前书': 5,
    '彼得后书': 3, '约翰一书': 5, '约翰二书': 1, '约翰三书': 1,
    '犹大书': 1, '启示录': 22,
  },
}

const issues = []
const warn = (type, book, title, detail) => issues.push({ type, book, title: title || '', detail })

// ========== 1. 章节覆盖核对 ==========
console.log('\n========== 1. 章节覆盖核对 ==========')
for (const t of ['ot', 'nt']) {
  const books = STD_CHAPTERS[t]
  for (const [bookName, stdCh] of Object.entries(books)) {
    const arts = all.filter(a => a._t === t && a.book === bookName && a.chapter > 0)
    if (arts.length === 0) {
      warn('章节缺失', bookName, '', `整卷无课程（应有${stdCh}章）`)
      continue
    }
    const maxCh = Math.max(...arts.map(a => a.chapter))
    const chapters = new Set(arts.map(a => a.chapter))
    // 标题中解析覆盖的章（如 "1 & 2"、"3~5"）
    let coveredMax = maxCh
    for (const a of arts) {
      const m = a.title.match(/(\d+)\s*[&～~和至\-–—]\s*(\d+)/)
      if (m) coveredMax = Math.max(coveredMax, parseInt(m[2]))
      const m2 = a.title.match(/(\d+):\d+\s*[~～\-–]\s*(?:\d+:)?\d+\s*[章]?/)
      // 如 "5:17~48" 不跨章
    }
    if (coveredMax < stdCh) {
      warn('章节偏少', bookName, '', `数据覆盖到第${coveredMax}章，圣经共${stdCh}章（${arts.length}篇课）`)
    }
  }
}
const chIssues = issues.filter(i => i.type === '章节缺失' || i.type === '章节偏少')
chIssues.forEach(i => console.log(`  [${i.type}] ${i.book}: ${i.detail}`))
console.log(`  → 章节问题: ${chIssues.length} 项`)

// ========== 2. 繁体字残留 ==========
console.log('\n========== 2. 繁体字残留 ==========')
// 高频繁体字（简体中不应出现）
const TRAD_CHARS = new Set(
  '們這國來時說對為會學經發關問開間門個東車馬長頁見貝言金們時經說關開問間門國來東車馬長頁見貝' +
  '萬與專業絲兩嚴喪豐臨麗舉麼義樂喬習鄉書買亂爭於雲亞產親億僅從倉倫儀價眾優偉傳傷偽體餘俠儉債傾儲兒黨寫軍農馮況凍淨準濁澤濟濱瀏滅燈靈災烏煙無煉煥燒燙營愛犧狀獨獻畫異發盜盡監盤盧礙礦積稱穩竊競箋簫糞糧緊繫繭繳纏罷羅肅脅腳臘臟興舊艦艱艷蘇蘭處虛蟲蠟襪覽觀詞詩話該詳誤語說調謀諾謂謝謹證識譚譯讀讓貝貞財貧貨販貪貫責貴買貶貸費貿賀賂資賈賊賓賜賞賠賢賣賤賦賭賴賺賽購贈贏贖趕趙趨躊躋躑躓躪躡車軌軍軒轉輪軟軻軸輕輛輟輩輝輯輸輻輿轄轅轆轍轎轟辭辯運過達違遙遜遞遲遷選遼遺邊邏醬鍋鍾鍵鎖鎮鏡鏽鑄鑰鑲針釘釣釗釙釜釣釤釥釦釧釩釪釬釭釮釯釰釱釲釳釴釵釶釷釸釹釺釻釼'
)
// 注意：部分字在简体中合法（如"於"作为叹词、"沉"的异体等），需排除误报
// 仅检测明确的繁体→简体映射字
const TRAD_MAP = {
  '們': '们', '這': '这', '國': '国', '來': '来', '時': '时', '說': '说',
  '對': '对', '為': '为', '會': '会', '學': '学', '經': '经', '發': '发',
  '關': '关', '問': '问', '開': '开', '間': '间', '門': '门', '個': '个',
  '東': '东', '車': '车', '馬': '马', '長': '长', '頁': '页', '見': '见',
  '貝': '贝', '萬': '万', '與': '与', '專': '专', '業': '业', '絲': '丝',
  '兩': '两', '嚴': '严', '豐': '丰', '臨': '临', '麗': '丽', '舉': '举',
  '麼': '么', '義': '义', '樂': '乐', '習': '习', '鄉': '乡', '書': '书',
  '買': '买', '亂': '乱', '爭': '争', '雲': '云', '亞': '亚', '產': '产',
  '親': '亲', '億': '亿', '從': '从', '倉': '仓', '倫': '伦', '儀': '仪',
  '們': '们', '價': '价', '眾': '众', '優': '优', '偉': '伟', '傳': '传',
  '傷': '伤', '偽': '伪', '體': '体', '餘': '余', '儉': '俭', '債': '债',
  '傾': '倾', '儲': '储', '兒': '儿', '黨': '党', '寫': '写', '軍': '军',
  '農': '农', '凍': '冻', '淨': '净', '準': '准', '濁': '浊', '澤': '泽',
  '濟': '济', '濱': '滨', '滅': '灭', '燈': '灯', '靈': '灵', '災': '灾',
  '烏': '乌', '煙': '烟', '無': '无', '煉': '炼', '煥': '焕', '燒': '烧',
  '燙': '烫', '營': '营', '愛': '爱', '犧': '牺', '狀': '状', '獨': '独',
  '獻': '献', '畫': '画', '異': '异', '盜': '盗', '盡': '尽', '監': '监',
  '盤': '盘', '盧': '卢', '礙': '碍', '礦': '矿', '積': '积', '稱': '称',
  '穩': '稳', '竊': '窃', '競': '竞', '糞': '粪', '糧': '粮', '緊': '紧',
  '繫': '系', '繭': '茧', '繳': '缴', '纏': '缠', '罷': '罢', '羅': '罗',
  '肅': '肃', '脅': '胁', '腳': '脚', '臘': '腊', '臟': '脏', '興': '兴',
  '舊': '旧', '艦': '舰', '艱': '艰', '艷': '艳', '蘇': '苏', '蘭': '兰',
  '處': '处', '虛': '虚', '蟲': '虫', '蠟': '蜡', '襪': '袜', '覽': '览',
  '觀': '观', '詞': '词', '詩': '诗', '話': '话', '詳': '详', '誤': '误',
  '語': '语', '調': '调', '謀': '谋', '諾': '诺', '謂': '谓', '謝': '谢',
  '謹': '谨', '證': '证', '識': '识', '譚': '谭', '譯': '译', '讀': '读',
  '讓': '让', '貞': '贞', '財': '财', '貧': '贫', '貨': '货', '販': '贩',
  '貪': '贪', '貫': '贯', '責': '责', '貴': '贵', '貶': '贬', '貸': '贷',
  '費': '费', '貿': '贸', '賀': '贺', '賂': '赂', '資': '资', '賈': '贾',
  '賊': '贼', '賓': '宾', '賜': '赐', '賞': '赏', '賠': '赔', '賢': '贤',
  '賣': '卖', '賤': '贱', '賦': '赋', '賭': '赌', '賴': '赖', '賺': '赚',
  '賽': '赛', '購': '购', '贈': '赠', '贏': '赢', '贖': '赎', '趕': '赶',
  '趙': '赵', '趨': '趋', '躊': '踌', '躋': '跻', '躑': '踯', '躓': '踬',
  '躪': '躏', '躡': '蹑', '軌': '轨', '軒': '轩', '轉': '转', '輪': '轮',
  '軟': '软', '軻': '轲', '軸': '轴', '輕': '轻', '輛': '辆', '輟': '辍',
  '輩': '辈', '輝': '辉', '輯': '辑', '輸': '输', '輻': '辐', '輿': '舆',
  '轄': '辖', '轅': '辕', '轆': '辘', '轍': '辙', '轎': '轿', '轟': '轰',
  '辭': '辞', '辯': '辩', '運': '运', '過': '过', '達': '达', '違': '违',
  '遙': '遥', '遜': '逊', '遞': '递', '遲': '迟', '遷': '迁', '選': '选',
  '遼': '辽', '遺': '遗', '邊': '边', '邏': '逻', '鍋': '锅', '鍾': '钟',
  '鍵': '键', '鎖': '锁', '鎮': '镇', '鏡': '镜', '鏽': '锈', '鑄': '铸',
  '鑰': '钥', '鑲': '镶', '針': '针', '釘': '钉', '釣': '钓', '釗': '钊',
  '銀': '银', '銅': '铜', '銘': '铭', '鋒': '锋', '錄': '录', '錦': '锦',
  '鍛': '锻', '鍛': '锻', '鏈': '链', '鏗': '铿', '鏘': '锵', '鐵': '铁',
  '鑽': '钻', '鑼': '锣', '長': '长', '門': '门', '問': '问', '聞': '闻',
  '閉': '闭', '閃': '闪', '閏': '闰', '閑': '闲', '間': '间', '閔': '闵',
  '閘': '闸', '閡': '阂', '閣': '阁', '閥': '阀', '閨': '闺', '閩': '闽',
  '閫': '阃', '閬': '阆', '閭': '闾', '閱': '阅', '閶': '阊', '閹': '阉',
  '閻': '阎', '閼': '阏', '閽': '阍', '閾': '阈', '閿': '阌', '闃': '阒',
  '闆': '板', '闇': '暗', '闈': '闱', '闊': '阔',
  '闋': '阕', '闌': '阑', '闍': '阇', '闐': '阗',
  '闓': '恺', '闔': '阖', '闕': '阙', '闖': '闯', '闚': '窥',
  '關': '关', '闡': '阐', '闢': '辟', '闤': '阛', '闥': '闼',
  '陽': '阳', '陰': '阴', '陳': '陈', '陸': '陆', '雲': '云', '電': '电',
  '靈': '灵', '靜': '静', '頂': '顶', '項': '项', '順': '顺', '須': '须',
  '頌': '颂', '預': '预', '頑': '顽', '頗': '颇', '頒': '颁', '頓': '顿',
  '領': '领', '頭': '头', '頰': '颊', '頸': '颈', '頤': '颐', '頻': '频',
  '頹': '颓', '類': '类', '風': '风', '飛': '飞', '餘': '余', '館': '馆',
  '餓': '饿', '饅': '馒',
  '馬': '马', '駕': '驾', '駐': '驻', '駝': '驼', '驚': '惊', '驕': '骄',
  '驗': '验', '髒': '脏', '鬆': '松', '鬥': '斗', '鬱': '郁',
  '魚': '鱼', '魯': '鲁', '鳥': '鸟', '鳴': '鸣', '鴻': '鸿', '鵲': '鹊',
  '鷹': '鹰', '鹽': '盐', '麥': '麦', '黃': '黄',
  '龍': '龙', '龜': '龟',
}
let tradCount = 0
const tradExamples = {}
for (const a of all) {
  const fullText = [a.title, ...a.paragraphs.map(p => p.text), a.answer || ''].join('\n')
  for (const [trad, simp] of Object.entries(TRAD_MAP)) {
    if (fullText.includes(trad)) {
      const count = fullText.split(trad).length - 1
      tradCount += count
      if (!tradExamples[trad]) tradExamples[trad] = { count: 0, simp, books: new Set() }
      tradExamples[trad].count += count
      tradExamples[trad].books.add(a.book)
    }
  }
}
const tradSorted = Object.entries(tradExamples).sort((x, y) => y[1].count - x[1].count)
if (tradSorted.length === 0) {
  console.log('  ✓ 未发现繁体字残留')
} else {
  console.log(`  共发现 ${tradCount} 处繁体字残留，涉及 ${tradSorted.length} 个字：`)
  tradSorted.slice(0, 30).forEach(([t, info]) => {
    console.log(`    ${t}→${info.simp} ×${info.count}  (${[...info.books].slice(0, 3).join('/')}${info.books.size > 3 ? '...' : ''})`)
  })
}

// ========== 3. 排版/格式问题 ==========
console.log('\n========== 3. 排版/格式问题 ==========')
let emptyPara = 0, htmlEntity = 0, htmlTag = 0, multiPunct = 0, shareJunk = 0
for (const a of all) {
  for (const p of a.paragraphs) {
    const t = p.text
    if (!t || !t.trim()) { emptyPara++; continue }
    if (/&[a-zA-Z]+;|&#\d+;/.test(t)) htmlEntity++
    if(/<\/?[a-zA-Z][^>]*>/.test(t) && !/^https?:/.test(t)) htmlTag++
    if (/[。！？]{2,}/.test(t)) multiPunct++
    if (/Share this|Share on|Like Loading|Loading\.\.\./.test(t)) shareJunk++
  }
}
console.log(`  空段落: ${emptyPara}`)
console.log(`  HTML实体残留(&nbsp;等): ${htmlEntity}`)
console.log(`  HTML标签残留(<br>等): ${htmlTag}`)
console.log(`  连续标点(。。等): ${multiPunct}`)
console.log(`  社交分享垃圾: ${shareJunk}`)

// ========== 4. 数据结构检查 ==========
console.log('\n========== 4. 数据结构检查 ==========')
let noParagraphs = 0, noUrl = 0, dupIds = 0, badStudyNo = 0
const idSet = new Set()
for (const a of all) {
  if (!a.paragraphs || a.paragraphs.length === 0) { noParagraphs++; warn('结构', a.book, a.title, '无段落内容') }
  if (!a.url) { noUrl++; warn('结构', a.book, a.title, '无url') }
  if (idSet.has(a.id)) { dupIds++; warn('结构', a.book, a.title, `重复id: ${a.id}`) }
  idSet.add(a.id)
  if (typeof a.studyNo !== 'number' || a.studyNo < 0) { badStudyNo++; warn('结构', a.book, a.title, `studyNo异常: ${a.studyNo}`) }
}
console.log(`  无段落文章: ${noParagraphs}`)
console.log(`  无url文章: ${noUrl}`)
console.log(`  重复id: ${dupIds}`)
console.log(`  studyNo异常: ${badStudyNo}`)

// ========== 5. 答案字段检查 ==========
console.log('\n========== 5. 答案字段检查 ==========')
let noAnswer = 0, shortAnswer = 0
for (const a of all) {
  if (a.studyNo === 9999) continue // 笔记无答案
  if (!a.answer || !a.answer.trim()) { noAnswer++; continue }
  if (a.answer.trim().length < 20) {
    shortAnswer++
    if (shortAnswer <= 10) console.log(`  答案过短 [${a.book}] ${a.title.slice(0, 30)}: "${a.answer.slice(0, 40)}"`)
  }
}
console.log(`  无答案的课程: ${noAnswer}`)
console.log(`  答案异常短(<20字): ${shortAnswer}`)

// ========== 6. 标题与内容一致性 ==========
console.log('\n========== 6. 标题/书卷名检查 ==========')
let bookMismatch = 0
const bookNames = new Set([...Object.keys(STD_CHAPTERS.ot), ...Object.keys(STD_CHAPTERS.nt)])
for (const a of all) {
  if (!bookNames.has(a.book)) {
    bookMismatch++
    warn('书卷名', a.book, a.title, `书卷名"${a.book}"不在标准列表中`)
  }
  // title 应包含书名或 Study
  if (a.studyNo !== 9999 && !/Study/i.test(a.title)) {
    warn('标题格式', a.book, a.title, '标题缺少 Study 标识')
  }
}
console.log(`  书卷名不匹配: ${bookMismatch}`)

// ========== 汇总 ==========
console.log('\n========== 审计汇总 ==========')
const byType = {}
issues.forEach(i => { byType[i.type] = (byType[i.type] || 0) + 1 })
console.log(byType)
console.log(`总问题数: ${issues.length}`)
