/**
 * 研经日课 - 新旧约读经数据
 * 来源：https://yimawusi.net 研经日课（繁体→简体）
 * 按圣经书卷顺序排列
 */

export interface Paragraph {
  tag: string
  text: string
}

export interface StudyArticle {
  id: string
  book: string
  /** 书卷在该约中的顺序：旧约1-39，新约1-27 */
  bookOrder: number
  chapter: number
  studyNo: number
  title: string
  url: string
  paragraphs: Paragraph[]
  answer?: string
}

/** 目录页所需的轻量元数据（不含正文 paragraphs 与 answer） */
export interface StudyArticleMeta {
  id: string
  book: string
  bookOrder: number
  chapter: number
  studyNo: number
  title: string
}

export type Testament = 'ot' | 'nt'

interface BookInfo {
  name: string
  order: number
}

/** 旧约39卷 */
export const OT_BOOKS: BookInfo[] = [
  { name: '创世记', order: 1 },
  { name: '出埃及记', order: 2 },
  { name: '利未记', order: 3 },
  { name: '民数记', order: 4 },
  { name: '申命记', order: 5 },
  { name: '约书亚记', order: 6 },
  { name: '士师记', order: 7 },
  { name: '路得记', order: 8 },
  { name: '撒母耳记上', order: 9 },
  { name: '撒母耳记下', order: 10 },
  { name: '列王纪上', order: 11 },
  { name: '列王纪下', order: 12 },
  { name: '历代志上', order: 13 },
  { name: '历代志下', order: 14 },
  { name: '以斯拉记', order: 15 },
  { name: '尼希米记', order: 16 },
  { name: '以斯帖记', order: 17 },
  { name: '约伯记', order: 18 },
  { name: '诗篇', order: 19 },
  { name: '箴言', order: 20 },
  { name: '传道书', order: 21 },
  { name: '雅歌', order: 22 },
  { name: '以赛亚书', order: 23 },
  { name: '耶利米书', order: 24 },
  { name: '耶利米哀歌', order: 25 },
  { name: '以西结书', order: 26 },
  { name: '但以理书', order: 27 },
  { name: '何西阿书', order: 28 },
  { name: '约珥书', order: 29 },
  { name: '阿摩司书', order: 30 },
  { name: '俄巴底亚书', order: 31 },
  { name: '约拿书', order: 32 },
  { name: '弥迦书', order: 33 },
  { name: '那鸿书', order: 34 },
  { name: '哈巴谷书', order: 35 },
  { name: '西番雅书', order: 36 },
  { name: '哈该书', order: 37 },
  { name: '撒迦利亚书', order: 38 },
  { name: '玛拉基书', order: 39 },
]

/** 新约27卷 */
export const NT_BOOKS: BookInfo[] = [
  { name: '马太福音', order: 1 },
  { name: '马可福音', order: 2 },
  { name: '路加福音', order: 3 },
  { name: '约翰福音', order: 4 },
  { name: '使徒行传', order: 5 },
  { name: '罗马书', order: 6 },
  { name: '哥林多前书', order: 7 },
  { name: '哥林多后书', order: 8 },
  { name: '加拉太书', order: 9 },
  { name: '以弗所书', order: 10 },
  { name: '腓立比书', order: 11 },
  { name: '歌罗西书', order: 12 },
  { name: '帖撒罗尼迦前书', order: 13 },
  { name: '帖撒罗尼迦后书', order: 14 },
  { name: '提摩太前书', order: 15 },
  { name: '提摩太后书', order: 16 },
  { name: '提多书', order: 17 },
  { name: '腓利门书', order: 18 },
  { name: '希伯来书', order: 19 },
  { name: '雅各书', order: 20 },
  { name: '彼得前书', order: 21 },
  { name: '彼得后书', order: 22 },
  { name: '约翰一书', order: 23 },
  { name: '约翰二书', order: 24 },
  { name: '约翰三书', order: 25 },
  { name: '犹大书', order: 26 },
  { name: '启示录', order: 27 },
]

/** 按约获取书卷列表 */
export function getBooks(testament: Testament): BookInfo[] {
  return testament === 'ot' ? OT_BOOKS : NT_BOOKS
}

// 缓存
const metaCache: Record<Testament, StudyArticleMeta[] | null> = { ot: null, nt: null }
const fullCache: Record<Testament, StudyArticle[] | null> = { ot: null, nt: null }

/** 加载目录页所需的轻量索引（仅元数据，约 60-100KB，秒开） */
export async function loadArticlesMeta(testament: Testament): Promise<StudyArticleMeta[]> {
  if (metaCache[testament]) return metaCache[testament]
  const mod = await import(`./${testament}_index.json`)
  const data = mod.default as StudyArticleMeta[]
  metaCache[testament] = data
  return data
}

/** 加载某约的全部文章全文（含正文与答案，体积较大，详情页按需使用） */
export async function loadArticles(testament: Testament): Promise<StudyArticle[]> {
  if (fullCache[testament]) return fullCache[testament]
  let data: StudyArticle[]
  if (testament === 'ot') {
    const mod = await import('./ot_articles.json')
    data = mod.default as StudyArticle[]
  } else {
    const mod = await import('./study_articles.json')
    data = mod.default as StudyArticle[]
  }
  fullCache[testament] = data
  return data
}

/**
 * 按 id 加载单篇文章全文（详情页按需加载）。
 * 策略：先查两约轻量索引（极小、秒回）定位所属约，再只加载该约全文数据。
 */
export async function loadArticleById(id: string): Promise<StudyArticle | undefined> {
  const [ntMeta, otMeta] = await Promise.all([loadArticlesMeta('nt'), loadArticlesMeta('ot')])
  const meta = ntMeta.find(a => a.id === id) ?? otMeta.find(a => a.id === id)
  if (!meta) return undefined
  const testament = OT_BOOKS.some(b => b.name === meta.book) ? 'ot' : 'nt'
  const all = await loadArticles(testament)
  return all.find(a => a.id === id)
}

/** 按 id 取相邻文章的元数据（用于详情页上一篇/下一篇，无需加载全文） */
export async function getNeighbors(id: string): Promise<{ prev?: StudyArticleMeta; next?: StudyArticleMeta }> {
  const [ntMeta, otMeta] = await Promise.all([loadArticlesMeta('nt'), loadArticlesMeta('ot')])
  const all = [...ntMeta, ...otMeta]
  const idx = all.findIndex(a => a.id === id)
  return {
    prev: idx > 0 ? all[idx - 1] : undefined,
    next: idx >= 0 && idx < all.length - 1 ? all[idx + 1] : undefined,
  }
}

/** 根据书卷名判断属于新约还是旧约 */
export function getTestamentByBook(bookName: string): Testament {
  return OT_BOOKS.some(b => b.name === bookName) ? 'ot' : 'nt'
}

/** 中文书卷名 → Bible Gateway 英文书卷名 */
const BOOK_EN: Record<string, string> = {
  '创世记': 'Genesis', '出埃及记': 'Exodus', '利未记': 'Leviticus',
  '民数记': 'Numbers', '申命记': 'Deuteronomy', '约书亚记': 'Joshua',
  '士师记': 'Judges', '路得记': 'Ruth',
  '撒母耳记上': '1 Samuel', '撒母耳记下': '2 Samuel',
  '列王纪上': '1 Kings', '列王纪下': '2 Kings',
  '历代志上': '1 Chronicles', '历代志下': '2 Chronicles',
  '以斯拉记': 'Ezra', '尼希米记': 'Nehemiah', '以斯帖记': 'Esther',
  '约伯记': 'Job', '诗篇': 'Psalms', '箴言': 'Proverbs',
  '传道书': 'Ecclesiastes', '雅歌': 'Song of Solomon',
  '以赛亚书': 'Isaiah', '耶利米书': 'Jeremiah', '耶利米哀歌': 'Lamentations',
  '以西结书': 'Ezekiel', '但以理书': 'Daniel',
  '何西阿书': 'Hosea', '约珥书': 'Joel', '阿摩司书': 'Amos',
  '俄巴底亚书': 'Obadiah', '约拿书': 'Jonah', '弥迦书': 'Micah',
  '那鸿书': 'Nahum', '哈巴谷书': 'Habakkuk', '西番雅书': 'Zephaniah',
  '哈该书': 'Haggai', '撒迦利亚书': 'Zechariah', '玛拉基书': 'Malachi',
  '马太福音': 'Matthew', '马可福音': 'Mark', '路加福音': 'Luke',
  '约翰福音': 'John', '使徒行传': 'Acts', '罗马书': 'Romans',
  '哥林多前书': '1 Corinthians', '哥林多后书': '2 Corinthians',
  '加拉太书': 'Galatians', '以弗所书': 'Ephesians', '腓立比书': 'Philippians',
  '歌罗西书': 'Colossians', '帖撒罗尼迦前书': '1 Thessalonians',
  '帖撒罗尼迦后书': '2 Thessalonians',
  '提摩太前书': '1 Timothy', '提摩太后书': '2 Timothy',
  '提多书': 'Titus', '腓利门书': 'Philemon', '希伯来书': 'Hebrews',
  '雅各书': 'James', '彼得前书': '1 Peter', '彼得后书': '2 Peter',
  '约翰一书': '1 John', '约翰二书': '2 John', '约翰三书': '3 John',
  '犹大书': 'Jude', '启示录': 'Revelation',
}

/**
 * 生成圣经原文链接（Bible Gateway 简体和合本 CUVS）
 * @param book 中文书卷名
 * @param chapter 章节号（0 或 9999 笔记时返回空）
 * @param title 文章标题，用于解析更精确的经文范围（如 3:19~4:7）
 */
export function getBibleLink(book: string, chapter: number, title?: string): string {
  const en = BOOK_EN[book]
  if (!en || !chapter || chapter === 9999) return ''
  // 尝试从标题解析经文范围，如 "加拉太书 3:19~4:7"
  let range = ''
  if (title) {
    const m = title.match(/(\d+:\d+[\s~～\-–]*\d*:\d*)/)
    if (m) range = m[1].replace(/[～~]/g, '-')
  }
  const search = range ? `${en} ${range}` : `${en} ${chapter}`
  return `https://www.biblegateway.com/passage/?search=${encodeURIComponent(search)}&version=CUVS`
}
