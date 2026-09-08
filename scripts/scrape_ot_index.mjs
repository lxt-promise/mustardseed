// 抓取旧约文章目录
import * as cheerio from 'cheerio'
import { writeFileSync } from 'fs'

const BASE = 'https://yimawusi.net/category/%e7%a0%94%e7%b6%93%e6%97%a5%e8%aa%b2/page/{}/'
const TOTAL_PAGES = 56

// 旧约39卷标准顺序（繁体）
const OT_ORDER = {
  '創世記': 1, '出埃及記': 2, '利未記': 3, '民數記': 4, '申命記': 5,
  '約書亞記': 6, '士師記': 7, '路得記': 8,
  '撒母耳記上': 9, '撒母耳記下': 10,
  '列王紀上': 11, '列王紀下': 12,
  '歷代志上': 13, '歷代志下': 14,
  '以斯拉記': 15, '尼希米記': 16, '以斯帖記': 17, '約伯記': 18,
  '詩篇': 19, '箴言': 20, '傳道書': 21, '雅歌': 22,
  '以賽亞書': 23, '耶利米書': 24, '耶利米哀歌': 25, '以西結書': 26, '但以理書': 27,
  '何西阿書': 28, '約珥書': 29, '阿摩司書': 30, '俄巴底亞書': 31, '約拿書': 32,
  '彌迦書': 33, '那鴻書': 34, '哈巴谷書': 35, '西番雅書': 36, '哈該書': 37,
  '撒迦利亞書': 38, '瑪拉基書': 39,
}

function detectOtBook(title) {
  // 精确匹配长书名
  for (const book of Object.keys(OT_ORDER)) {
    if (title.includes(book)) return book
  }
  // 需区分上下的
  if (title.includes('撒母耳記上') || title.includes('撒母耳上')) return '撒母耳記上'
  if (title.includes('撒母耳記下') || title.includes('撒母耳下')) return '撒母耳記下'
  if (title.includes('列王紀上') || title.includes('列王上')) return '列王紀上'
  if (title.includes('列王紀下') || title.includes('列王下')) return '列王紀下'
  if (title.includes('歷代志上') || title.includes('历代志上')) return '歷代志上'
  if (title.includes('歷代志下') || title.includes('历代志下')) return '歷代志下'
  // 简称兜底
  const shortMap = {
    '創世': '創世記', '出埃及': '出埃及記', '利未': '利未記', '民數': '民數記', '民数': '民數記',
    '申命': '申命記', '約書亞': '約書亞記', '士師': '士師記', '路得': '路得記',
    '以斯拉': '以斯拉記', '尼希米': '尼希米記', '以斯帖': '以斯帖記', '約伯': '約伯記',
    '詩': '詩篇', '箴': '箴言', '傳道': '傳道書', '雅歌': '雅歌',
    '以賽亞': '以賽亞書', '耶利米': '耶利米書', '哀歌': '耶利米哀歌',
    '以西結': '以西結書', '但以理': '但以理書',
    '何西阿': '何西阿書', '約珥': '約珥書', '阿摩司': '阿摩司書', '俄巴底亞': '俄巴底亞書',
    '約拿': '約拿書', '彌迦': '彌迦書', '那鴻': '那鴻書', '哈巴谷': '哈巴谷書',
    '西番雅': '西番雅書', '哈該': '哈該書', '撒迦利亞': '撒迦利亞書', '瑪拉基': '瑪拉基書',
  }
  for (const [short, full] of Object.entries(shortMap)) {
    if (title.includes(short)) return full
  }
  return null
}

function parseStudyNumber(title) {
  const m = title.match(/Study\s+(\d+)/i)
  return m ? parseInt(m[1], 10) : 9999
}

async function fetchPage(url) {
  const res = await fetch(url, { headers: { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)' } })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.text()
}

async function main() {
  const allItems = []
  const seenUrls = new Set()

  for (let page = 1; page <= TOTAL_PAGES; page++) {
    const url = BASE.replace('{}', page)
    try {
      const html = await fetchPage(url)
      const $ = cheerio.load(html)
      $('h2 a').each((i, el) => {
        const title = $(el).text().trim()
        const link = $(el).attr('href')
        if (!link || seenUrls.has(link)) return
        seenUrls.add(link)
        const book = detectOtBook(title)
        allItems.push({ title, url: link, ot_book: book, page, study_no: parseStudyNumber(title) })
      })
      console.log(`page ${page}/${TOTAL_PAGES} done, total: ${allItems.length}`)
    } catch (e) {
      console.error(`[WARN] page ${page} failed: ${e.message}`)
    }
    await new Promise(r => setTimeout(r, 250))
  }

  const otItems = allItems.filter(i => i.ot_book)
  otItems.sort((a, b) => {
    const oa = OT_ORDER[a.ot_book], ob = OT_ORDER[b.ot_book]
    if (oa !== ob) return oa - ob
    if (a.study_no !== b.study_no) return a.study_no - b.study_no
    return a.title.localeCompare(b.title)
  })

  console.log(`\n=== 总计: ${allItems.length} 篇，其中旧约 ${otItems.length} 篇 ===\n`)
  const cnt = {}
  for (const it of otItems) cnt[it.ot_book] = (cnt[it.ot_book] || 0) + 1
  for (const book of Object.keys(OT_ORDER)) {
    if (cnt[book]) console.log(`  ${book}: ${cnt[book]} 篇`)
  }

  writeFileSync('ot_index.json', JSON.stringify(otItems, null, 2), 'utf-8')
  console.log('\n旧约列表已保存到 ot_index.json')
}

main()
