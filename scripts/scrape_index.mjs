// 抓取 yimawusi.net 研经日课目录，过滤新约文章
import * as cheerio from 'cheerio'
import { writeFileSync } from 'fs'

const BASE = 'https://yimawusi.net/category/%e7%a0%94%e7%b6%93%e6%97%a5%e8%aa%b2/page/{}/'
const TOTAL_PAGES = 56

// 新约书卷标准顺序（27卷，繁体）
const NT_ORDER = {
  '馬太福音': 1, '馬可福音': 2, '路加福音': 3, '約翰福音': 4,
  '使徒行傳': 5, '羅馬書': 6, '哥林多前書': 7, '哥林多後書': 8,
  '加拉太書': 9, '以弗所書': 10, '腓立比書': 11, '歌羅西書': 12,
  '帖撒羅尼迦前書': 13, '帖撒羅尼迦後書': 14,
  '提摩太前書': 15, '提摩太後書': 16, '提多書': 17, '腓利門書': 18,
  '希伯來書': 19, '雅各書': 20, '彼得前書': 21, '彼得後書': 22,
  '約翰一書': 23, '約翰二書': 24, '約翰三書': 25, '猶大書': 26, '啟示錄': 27,
}

/** 从标题识别新约书卷，返回标准书卷名；非新约返回 null */
function detectNtBook(title) {
  // 约翰书信用大写数字：壹/貳/叁
  if (title.includes('約翰壹書') || title.includes('约翰一书')) return '約翰一書'
  if (title.includes('約翰貳書') || title.includes('约翰二书')) return '約翰二書'
  if (title.includes('約翰叁書') || title.includes('约翰三书')) return '約翰三書'
  // 先精确匹配长书名（避免"約翰"误匹配到福音）
  for (const book of Object.keys(NT_ORDER)) {
    if (title.includes(book)) return book
  }
  // 需区分前/后的，单独处理
  if (title.includes('哥林多前')) return '哥林多前書'
  if (title.includes('哥林多後') || title.includes('哥林多后')) return '哥林多後書'
  if (title.includes('帖撒羅尼迦前')) return '帖撒羅尼迦前書'
  if (title.includes('帖撒羅尼迦後') || title.includes('帖撒羅尼迦后')) return '帖撒羅尼迦後書'
  if (title.includes('提摩太前')) return '提摩太前書'
  if (title.includes('提摩太後') || title.includes('提摩太后')) return '提摩太後書'
  if (title.includes('彼得前')) return '彼得前書'
  if (title.includes('彼得後') || title.includes('彼得后')) return '彼得後書'
  // 简称兜底
  const shortMap = {
    '馬太': '馬太福音', '馬可': '馬可福音', '路加': '路加福音',
    '約翰': '約翰福音',  // 約翰福音、書信已精确匹配，这里兜底
    '羅馬': '羅馬書',
    '加拉太': '加拉太書', '以弗所': '以弗所書', '腓立比': '腓立比書',
    '歌羅西': '歌羅西書', '提多': '提多書', '腓利門': '腓利門書',
    '希伯來': '希伯來書', '雅各': '雅各書', '猶大': '猶大書', '啟示': '啟示錄',
  }
  for (const [short, full] of Object.entries(shortMap)) {
    if (title.includes(short)) return full
  }
  return null
}

/** 提取 Study N 编号，用于同卷内排序；非 Study 格式返回 9999 */
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
        const book = detectNtBook(title)
        allItems.push({
          title,
          url: link,
          nt_book: book,
          page,
          study_no: parseStudyNumber(title),
        })
      })
      console.log(`page ${page}/${TOTAL_PAGES} done, total: ${allItems.length}`)
    } catch (e) {
      console.error(`[WARN] page ${page} failed: ${e.message}`)
    }
    // 礼貌延迟
    await new Promise(r => setTimeout(r, 250))
  }

  const ntItems = allItems.filter(i => i.nt_book)
  ntItems.sort((a, b) => {
    const oa = NT_ORDER[a.nt_book], ob = NT_ORDER[b.nt_book]
    if (oa !== ob) return oa - ob
    if (a.study_no !== b.study_no) return a.study_no - b.study_no
    return a.title.localeCompare(b.title)
  })

  console.log(`\n=== 总计: ${allItems.length} 篇，其中新约 ${ntItems.length} 篇 ===\n`)

  // 按卷统计
  const cnt = {}
  for (const it of ntItems) cnt[it.nt_book] = (cnt[it.nt_book] || 0) + 1
  for (const book of Object.keys(NT_ORDER)) {
    if (cnt[book]) console.log(`  ${book}: ${cnt[book]} 篇`)
  }

  // 非新约文章（看看有哪些，供判断是否遗漏）
  const nonNt = allItems.filter(i => !i.nt_book)
  console.log(`\n=== 非新约（共 ${nonNt.length} 篇）标题示例（前40条）===`)
  nonNt.slice(0, 40).forEach(i => console.log(`  page${i.page}: ${i.title}`))

  writeFileSync('nt_index.json', JSON.stringify(ntItems, null, 2), 'utf-8')
  console.log(`\n新约列表已保存到 nt_index.json`)
}

main()
