// 抓取旧约文章详情页（正文 + 评论区答案），繁体转简体
import * as cheerio from 'cheerio'
import OpenCC from 'opencc-js'
import { readFileSync, writeFileSync, existsSync } from 'fs'

const converter = OpenCC.Converter({ from: 'tw', to: 'cn' })

// 繁→简 书卷名映射（旧约）
const BOOK_T2S = {
  '創世記': '创世记', '出埃及記': '出埃及记', '利未記': '利未记', '民數記': '民数记', '申命記': '申命记',
  '約書亞記': '约书亚记', '士師記': '士师记', '路得記': '路得记',
  '撒母耳記上': '撒母耳记上', '撒母耳記下': '撒母耳记下',
  '列王紀上': '列王纪上', '列王紀下': '列王纪下',
  '歷代志上': '历代志上', '歷代志下': '历代志下',
  '以斯拉記': '以斯拉记', '尼希米記': '尼希米记', '以斯帖記': '以斯帖记', '約伯記': '约伯记',
  '詩篇': '诗篇', '箴言': '箴言', '傳道書': '传道书', '雅歌': '雅歌',
  '以賽亞書': '以赛亚书', '耶利米書': '耶利米书', '耶利米哀歌': '耶利米哀歌', '以西結書': '以西结书', '但以理書': '但以理书',
  '何西阿書': '何西阿书', '約珥書': '约珥书', '阿摩司書': '阿摩司书', '俄巴底亞書': '俄巴底亚书', '約拿書': '约拿书',
  '彌迦書': '弥迦书', '那鴻書': '那鸿书', '哈巴谷書': '哈巴谷书', '西番雅書': '西番雅书', '哈該書': '哈该书',
  '撒迦利亞書': '撒迦利亚书', '瑪拉基書': '玛拉基书',
}
const OT_ORDER_S = {
  '创世记': 1, '出埃及记': 2, '利未记': 3, '民数记': 4, '申命记': 5,
  '约书亚记': 6, '士师记': 7, '路得记': 8,
  '撒母耳记上': 9, '撒母耳记下': 10,
  '列王纪上': 11, '列王纪下': 12,
  '历代志上': 13, '历代志下': 14,
  '以斯拉记': 15, '尼希米记': 16, '以斯帖记': 17, '约伯记': 18,
  '诗篇': 19, '箴言': 20, '传道书': 21, '雅歌': 22,
  '以赛亚书': 23, '耶利米书': 24, '耶利米哀歌': 25, '以西结书': 26, '但以理书': 27,
  '何西阿书': 28, '约珥书': 29, '阿摩司书': 30, '俄巴底亚书': 31, '约拿书': 32,
  '弥迦书': 33, '那鸿书': 34, '哈巴谷书': 35, '西番雅书': 36, '哈该书': 37,
  '撒迦利亚书': 38, '玛拉基书': 39,
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

function parseChapter(title, book) {
  const afterBook = title.slice(title.indexOf(book) + book.length)
  const m = afterBook.match(/(\d+)/)
  return m ? parseInt(m[1], 10) : 0
}

function slugFromUrl(url) {
  const m = url.match(/\/(\d{4}\/\d{2}\/\d{2}\/[^/]+)\/?$/)
  return m ? m[1] : url
}

function extractContent($, $content) {
  const blocks = []
  $content.children().each((i, el) => {
    const tag = (el.tagName || 'p').toLowerCase()
    const text = $(el).text().trim()
    if (!text || tag === 'script' || tag === 'style') return
    blocks.push({ tag, text: converter(text) })
  })
  return blocks
}

async function main() {
  const index = JSON.parse(readFileSync('ot_index.json', 'utf-8'))
  const outFile = 'ot_articles.json'
  const done = existsSync(outFile) ? JSON.parse(readFileSync(outFile, 'utf-8')) : []
  const doneUrls = new Set(done.map(a => a.url))
  console.log(`已抓取 ${done.length} 篇，待抓取 ${index.length - doneUrls.size} 篇`)

  for (let i = 0; i < index.length; i++) {
    const item = index[i]
    if (doneUrls.has(item.url)) continue

    process.stdout.write(`[${i + 1}/${index.length}] ${item.title.slice(0, 35)}... `)
    try {
      const html = await fetchPage(item.url)
      const $ = cheerio.load(html)
      const $content = $('.entry-content')
      const blocks = extractContent($, $content)

      // 抓取评论区第一条评论作为答案
      let answer = ''
      const $comments = $('#comments .comment-content')
      if ($comments.length > 0) {
        answer = converter($($comments[0]).text().trim())
      }

      const bookS = BOOK_T2S[item.ot_book] || item.ot_book
      done.push({
        id: slugFromUrl(item.url),
        book: bookS,
        bookOrder: OT_ORDER_S[bookS] || 99,
        chapter: parseChapter(converter(item.title), bookS),
        studyNo: parseStudyNumber(item.title),
        title: converter(item.title),
        url: item.url,
        paragraphs: blocks,
        answer,
      })
      process.stdout.write(`OK (${blocks.length}段${answer ? ', 有答案' : ''})\n`)
    } catch (e) {
      process.stdout.write(`FAIL: ${e.message}\n`)
    }

    if (done.length % 10 === 0) {
      writeFileSync(outFile, JSON.stringify(done, null, 2), 'utf-8')
    }
    await new Promise(r => setTimeout(r, 200))
  }

  // 排序：书卷顺序 → 章节号 → Study编号
  done.sort((a, b) => {
    if (a.bookOrder !== b.bookOrder) return a.bookOrder - b.bookOrder
    if (a.chapter !== b.chapter) return a.chapter - b.chapter
    if (a.studyNo !== b.studyNo) return a.studyNo - b.studyNo
    return a.title.localeCompare(b.title, 'zh')
  })
  writeFileSync(outFile, JSON.stringify(done, null, 2), 'utf-8')
  console.log(`\n完成！共抓取 ${done.length} 篇，已保存到 ${outFile}`)
}

main()
