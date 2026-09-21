/**
 * 把整约全文 JSON 按书卷拆成小块，供前端按需加载（分章缓存）。
 *
 * 输入：frontend/src/data/ot_articles.json / study_articles.json
 * 输出：frontend/src/data/articles/ot/<bookOrder>.json
 *       frontend/src/data/articles/nt/<bookOrder>.json
 *
 * 用法：node scripts/split_books.mjs
 * 数据更新（重新抓取/修订整约 JSON）后需重跑本脚本。
 */
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const DATA_DIR = join(root, 'frontend', 'src', 'data')

function split(sourceFile, testament) {
  const articles = JSON.parse(readFileSync(join(DATA_DIR, sourceFile), 'utf8'))
  const groups = new Map()
  for (const a of articles) {
    const key = a.bookOrder
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key).push(a)
  }
  const outDir = join(DATA_DIR, 'articles', testament)
  mkdirSync(outDir, { recursive: true })
  let totalBytes = 0
  for (const [order, list] of groups) {
    list.sort((a, b) => a.chapter - b.chapter || a.studyNo - b.studyNo)
    const json = JSON.stringify(list)
    writeFileSync(join(outDir, `${order}.json`), json)
    totalBytes += json.length
  }
  console.log(`${testament}: ${groups.size} 卷, ${articles.length} 篇, ${(totalBytes / 1024).toFixed(0)} KB`)
}

split('ot_articles.json', 'ot')
split('study_articles.json', 'nt')
