// 补充新约文章的答案部分（抓取评论区第一条评论，繁转简）
import * as cheerio from 'cheerio'
import OpenCC from 'opencc-js'
import { readFileSync, writeFileSync } from 'fs'

const converter = OpenCC.Converter({ from: 'tw', to: 'cn' })
const DATA_FILE = '../frontend/src/data/study_articles.json'

const articles = JSON.parse(readFileSync(DATA_FILE, 'utf-8'))

async function fetchPage(url) {
  const res = await fetch(url, { headers: { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)' } })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.text()
}

let added = 0
let skipped = 0
let noComment = 0

for (let i = 0; i < articles.length; i++) {
  const a = articles[i]
  // 已有答案则跳过
  if (a.answer && a.answer.trim()) { skipped++; continue }

  process.stdout.write(`[${i + 1}/${articles.length}] ${a.title.slice(0, 35)}... `)
  try {
    const html = await fetchPage(a.url)
    const $ = cheerio.load(html)
    const $comments = $('#comments .comment-content')
    if ($comments.length === 0) {
      a.answer = ''
      noComment++
      process.stdout.write('无评论\n')
    } else {
      // 第一条评论是站长的参考答案
      const raw = $($comments[0]).text().trim()
      a.answer = converter(raw)
      added++
      process.stdout.write(`OK (${a.answer.length}字)\n`)
    }
  } catch (e) {
    a.answer = ''
    process.stdout.write(`FAIL: ${e.message}\n`)
  }

  // 每20篇保存一次
  if ((i + 1) % 20 === 0) {
    writeFileSync(DATA_FILE, JSON.stringify(articles), 'utf-8')
  }
  await new Promise(r => setTimeout(r, 200))
}

writeFileSync(DATA_FILE, JSON.stringify(articles), 'utf-8')
console.log(`\n完成！新增答案 ${added} 篇，已有跳过 ${skipped} 篇，无评论 ${noComment} 篇`)
