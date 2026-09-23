/**
 * 把整约全文 JSON 按书卷 → 章节拆成小块，供前端按需加载（分章缓存）。
 *
 * 输入：frontend/src/data/ot_articles.json / study_articles.json
 * 输出：frontend/src/data/articles/<ot|nt>/<bookOrder>/<chapter>.json
 *       同章多篇（studyNo 不同）归在同一个章块内；chapter=0 为卷导言。
 *
 * 用法：node scripts/split_books.mjs
 * 数据更新（重新抓取/修订整约 JSON）后需重跑本脚本。
 */
import { readFileSync, writeFileSync, mkdirSync, rmSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const DATA_DIR = join(root, 'frontend', 'src', 'data')

function split(sourceFile, testament) {
  const articles = JSON.parse(readFileSync(join(DATA_DIR, sourceFile), 'utf8'))
  // key = bookOrder/chapter
  const groups = new Map()
  for (const a of articles) {
    const key = `${a.bookOrder}/${a.chapter}`
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key).push(a)
  }
  const baseDir = join(DATA_DIR, 'articles', testament)
  rmSync(baseDir, { recursive: true, force: true })
  let totalBytes = 0
  let max = 0
  for (const [key, list] of groups) {
    list.sort((a, b) => a.chapter - b.chapter || a.studyNo - b.studyNo)
    const json = JSON.stringify(list)
    const [bookOrder, chapter] = key.split('/')
    const outFile = join(baseDir, bookOrder, `${chapter}.json`)
    mkdirSync(dirname(outFile), { recursive: true })
    writeFileSync(outFile, json)
    totalBytes += json.length
    max = Math.max(max, json.length)
  }
  console.log(`${testament}: ${groups.size} 个章块, ${articles.length} 篇, ${(totalBytes / 1024).toFixed(0)} KB, 最大 ${(max / 1024).toFixed(0)} KB`)
}

split('ot_articles.json', 'ot')
split('study_articles.json', 'nt')
