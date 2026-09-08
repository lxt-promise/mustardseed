// 将抓取的文章数据转换为前端可用的格式，添加章节号并按章分组排序
import { readFileSync, writeFileSync } from 'fs'

const articles = JSON.parse(readFileSync('../frontend/src/data/study_articles.json', 'utf-8'))

/**
 * 从标题中提取起始章节号
 * 例如："Study 5 马太福音 5:1~16 (3.1.9)" -> 5
 *       "Study 12 马太福音 8:23~9:8 (3.1.30)" -> 8
 *       "Study 1 马太福音 1 (3.1.5)" -> 1
 *       "约翰贰书 & 约翰叁书" -> 0（无明确章节）
 */
function parseChapter(title, book) {
  // 去掉书卷名，找后面的第一个数字
  const afterBook = title.slice(title.indexOf(book) + book.length)
  const m = afterBook.match(/(\d+)/)
  return m ? parseInt(m[1], 10) : 0
}

// 添加章节号
for (const a of articles) {
  a.chapter = parseChapter(a.title, a.book)
}

// 排序：书卷顺序 → 章节号 → Study编号
articles.sort((a, b) => {
  if (a.bookOrder !== b.bookOrder) return a.bookOrder - b.bookOrder
  if (a.chapter !== b.chapter) return a.chapter - b.chapter
  if (a.studyNo !== b.studyNo) return a.studyNo - b.studyNo
  return a.title.localeCompare(b.title, 'zh')
})

// 写出压缩版 JSON 到前端数据目录
const outPath = '../frontend/src/data/study_articles.json'
writeFileSync(outPath, JSON.stringify(articles), 'utf-8')
console.log(`已生成 ${outPath}`)
console.log(`共 ${articles.length} 篇文章`)

// 统计每卷的章节数
const bookChapters = {}
for (const a of articles) {
  if (!bookChapters[a.book]) bookChapters[a.book] = new Set()
  bookChapters[a.book].add(a.chapter)
}
console.log('\n各卷章节数:')
for (const [book, chapters] of Object.entries(bookChapters)) {
  console.log(`  ${book}: ${chapters.size} 章`)
}
