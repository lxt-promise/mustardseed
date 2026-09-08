/**
 * 数据修复脚本：
 * 1. 修正 chapter 字段（单章书卷恒为1；多章书卷正确提取书名后起始章号；处理壹贰叁书名变体）
 * 2. 删除社交分享垃圾 div 段落（保留补充资料类 div）
 * 3. 修复连续标点（。。 / ！。）
 * 4. 重新按 bookOrder → chapter → studyNo 排序
 */
import { readFileSync, writeFileSync } from 'fs'
import { fileURLToPath } from 'url'
import { dirname, join } from 'path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const dataDir = join(__dirname, '..', 'frontend', 'src', 'data')

// 单章书卷（圣经总章数=1），节号不应被当作章号
const SINGLE_CHAPTER_BOOKS = new Set(['俄巴底亚书', '腓利门书', '约翰二书', '约翰三书', '犹大书'])

// 书名在标题中可能出现的变体（繁体数字）
const BOOK_TITLE_VARIANTS = {
  '约翰一书': ['约翰一书', '约翰壹书'],
  '约翰二书': ['约翰二书', '约翰贰书'],
  '约翰三书': ['约翰三书', '约翰叁书'],
}

/** 正确计算章节号 */
function fixChapter(article) {
  if (article.studyNo === 9999) return 0 // 研读笔记
  if (SINGLE_CHAPTER_BOOKS.has(article.book)) return 1 // 单章书卷
  // 去掉标题末尾的日期编号括号，如 "(1.1.26)"
  const title = article.title.replace(/\s*\(\d+(?:\.\d+)*\)\s*$/, '')
  // 找书名位置（含繁体数字变体）
  const variants = BOOK_TITLE_VARIANTS[article.book] || [article.book]
  let afterBook = null
  for (const v of variants) {
    const idx = title.indexOf(v)
    if (idx >= 0) { afterBook = title.slice(idx + v.length); break }
  }
  if (afterBook === null) afterBook = title
  const m = afterBook.match(/(\d+)/)
  return m ? parseInt(m[1], 10) : 0
}

/** 是否为社交分享垃圾段落 */
function isShareJunk(p) {
  return p.tag === 'div' && /Share this|Share on|Like Loading|Loading\.\.\.|^Related/.test(p.text)
}

/** 修复文本标点 */
function fixText(text) {
  return text
    .replace(/。。+/g, '。')
    .replace(/！。/g, '！')
    .replace(/？。/g, '？')
}

function processFile(file) {
  const path = join(dataDir, file)
  const data = JSON.parse(readFileSync(path, 'utf8'))
  let chapterFixes = 0
  let junkRemoved = 0
  let punctFixes = 0

  for (const a of data) {
    // 修复章节号
    const newCh = fixChapter(a)
    if (newCh !== a.chapter) {
      chapterFixes++
      console.log(`  [章节] ${a.book} "${a.title.slice(0, 32)}" : ${a.chapter} → ${newCh}`)
      a.chapter = newCh
    }
    // 删除垃圾段落 + 修复标点
    a.paragraphs = a.paragraphs.filter(p => {
      if (isShareJunk(p)) { junkRemoved++; return false }
      return true
    })
    for (const p of a.paragraphs) {
      const fixed = fixText(p.text)
      if (fixed !== p.text) { punctFixes++; p.text = fixed }
    }
    if (a.answer) {
      const fixed = fixText(a.answer)
      if (fixed !== a.answer) { punctFixes++; a.answer = fixed }
    }
  }

  // 重新排序：书卷 → 章节 → Study编号
  data.sort((a, b) => {
    if (a.bookOrder !== b.bookOrder) return a.bookOrder - b.bookOrder
    if (a.chapter !== b.chapter) return a.chapter - b.chapter
    if (a.studyNo !== b.studyNo) return a.studyNo - b.studyNo
    return a.title.localeCompare(b.title, 'zh')
  })

  writeFileSync(path, JSON.stringify(data), 'utf8')
  console.log(`\n${file}: ${data.length} 篇 | 章节修正 ${chapterFixes} | 垃圾段删除 ${junkRemoved} | 标点修正 ${punctFixes}`)
}

console.log('===== 修复旧约 =====')
processFile('ot_articles.json')
console.log('\n===== 修复新约 =====')
processFile('study_articles.json')
console.log('\n✓ 完成')
