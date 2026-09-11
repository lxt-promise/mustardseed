/**
 * 生成研经日课轻量索引文件（仅目录所需元数据，不含正文/答案）
 * 用途：目录页秒开，点击后再按需加载单篇全文
 *
 * 输入：frontend/src/data/study_articles.json (新约) + ot_articles.json (旧约)
 * 输出：frontend/src/data/nt_index.json + ot_index.json
 */
import { readFileSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const DATA_DIR = join(__dirname, '..', 'frontend', 'src', 'data')

function buildIndex(fullPath, testament) {
  const full = JSON.parse(readFileSync(fullPath, 'utf-8'))
  const index = full.map(a => ({
    id: a.id,
    book: a.book,
    bookOrder: a.bookOrder,
    chapter: a.chapter,
    studyNo: a.studyNo,
    title: a.title,
  }))
  const outPath = join(DATA_DIR, `${testament}_index.json`)
  writeFileSync(outPath, JSON.stringify(index), 'utf-8')
  console.log(`${testament}: ${full.length} 篇 → ${outPath}`)
  console.log(`  原始: ${(readFileSync(fullPath).length / 1024).toFixed(1)} KB`)
  console.log(`  索引: ${(readFileSync(outPath).length / 1024).toFixed(1)} KB`)
  return index
}

buildIndex(join(DATA_DIR, 'study_articles.json'), 'nt')
buildIndex(join(DATA_DIR, 'ot_articles.json'), 'ot')
console.log('✅ 索引生成完成')
