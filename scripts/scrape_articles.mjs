// 抓取新约文章详情页内容，繁体转简体，支持断点续传
import * as cheerio from 'cheerio'
import OpenCC from 'opencc-js'
import { readFileSync, writeFileSync, existsSync } from 'fs'

const converter = OpenCC.Converter({ from: 'tw', to: 'cn' })

// 繁→简 书卷名映射
const BOOK_T2S = {
  '馬太福音': '马太福音', '馬可福音': '马可福音', '路加福音': '路加福音', '約翰福音': '约翰福音',
  '使徒行傳': '使徒行传', '羅馬書': '罗马书', '哥林多前書': '哥林多前书', '哥林多後書': '哥林多后书',
  '加拉太書': '加拉太书', '以弗所書': '以弗所书', '腓立比書': '腓立比书', '歌羅西書': '歌罗西书',
  '帖撒羅尼迦前書': '帖撒罗尼迦前书', '帖撒羅尼迦後書': '帖撒罗尼迦后书',
  '提摩太前書': '提摩太前书', '提摩太後書': '提摩太后书', '提多書': '提多书', '腓利門書': '腓利门书',
  '希伯來書': '希伯来书', '雅各書': '雅各书', '彼得前書': '彼得前书', '彼得後書': '彼得后书',
  '約翰一書': '约翰一书', '約翰二書': '约翰二书', '約翰三書': '约翰三书', '猶大書': '犹大书', '啟示錄': '启示录',
}
const NT_ORDER_S = {
  '马太福音': 1, '马可福音': 2, '路加福音': 3, '约翰福音': 4, '使徒行传': 5, '罗马书': 6,
  '哥林多前书': 7, '哥林多后书': 8, '加拉太书': 9, '以弗所书': 10, '腓立比书': 11, '歌罗西书': 12,
  '帖撒罗尼迦前书': 13, '帖撒罗尼迦后书': 14, '提摩太前书': 15, '提摩太后书': 16, '提多书': 17, '腓利门书': 18,
  '希伯来书': 19, '雅各书': 20, '彼得前书': 21, '彼得后书': 22, '约翰一书': 23, '约翰二书': 24,
  '约翰三书': 25, '犹大书': 26, '启示录': 27,
}

async function fetchPage(url) {
  const res = await fetch(url, { headers: { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)' } })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.text()
}

function parseStudyNumber(title) {
  const m = title.match(/Study\s+(\d+)/i)
  return m ? parseInt(m[1], 10) : 9999
}

// 从 URL 提取 slug 作为 id
function slugFromUrl(url) {
  const m = url.match(/\/(\d{4}\/\d{2}\/\d{2}\/[^/]+)\/?$/)
  return m ? m[1] : url
}

function extractContent($, $content) {
  const blocks = []
  $content.children().each((i, el) => {
    const tag = (el.tagName || 'p').toLowerCase()
    const text = $(el).text().trim()
    if (!text) return
    // 跳过脚本和样式
    if (tag === 'script' || tag === 'style') return
    blocks.push({ tag, text: converter(text) })
  })
  return blocks
}

async function main() {
  const index = JSON.parse(readFileSync('nt_index.json', 'utf-8'))
  const outFile = 'nt_articles.json'

  // 断点续传：已抓取的跳过
  const done = existsSync(outFile) ? JSON.parse(readFileSync(outFile, 'utf-8')) : []
  const doneUrls = new Set(done.map(a => a.url))
  console.log(`已抓取 ${done.length} 篇，待抓取 ${index.length - doneUrls.size} 篇`)

  for (let i = 0; i < index.length; i++) {
    const item = index[i]
    if (doneUrls.has(item.url)) continue

    process.stdout.write(`[${i + 1}/${index.length}] ${item.title.slice(0, 40)}... `)
    try {
      const html = await fetchPage(item.url)
      const $ = cheerio.load(html)
      const $content = $('.entry-content')
      const blocks = extractContent($, $content)

      const bookS = BOOK_T2S[item.nt_book] || item.nt_book
      done.push({
        id: slugFromUrl(item.url),
        book: bookS,
        bookOrder: NT_ORDER_S[bookS] || 99,
        studyNo: parseStudyNumber(item.title),
        title: converter(item.title),
        url: item.url,
        paragraphs: blocks,
      })
      process.stdout.write(`OK (${blocks.length}段)\n`)
    } catch (e) {
      process.stdout.write(`FAIL: ${e.message}\n`)
    }

    // 每10篇保存一次
    if (done.length % 10 === 0) {
      writeFileSync(outFile, JSON.stringify(done, null, 2), 'utf-8')
    }
    await new Promise(r => setTimeout(r, 200))
  }

  // 最终保存并排序
  done.sort((a, b) => {
    if (a.bookOrder !== b.bookOrder) return a.bookOrder - b.bookOrder
    if (a.studyNo !== b.studyNo) return a.studyNo - b.studyNo
    return a.title.localeCompare(b.title, 'zh')
  })
  writeFileSync(outFile, JSON.stringify(done, null, 2), 'utf-8')
  console.log(`\n完成！共抓取 ${done.length} 篇，已保存到 ${outFile}`)
}

main()
