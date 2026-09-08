/**
 * 访问统计（百度统计）
 *
 * ┌─────────────────────────────────────────────┐
 * │  开关：设为 false 即完全关闭统计（不加载脚本）  │
 * └─────────────────────────────────────────────┘
 */
export const BAIDU_ANALYTICS_ENABLED = false

/** 百度统计站点 ID（后台"代码获取"里 hm.js? 后面的那串） */
const BAIDU_SITE_ID = 'e9ddc225e7ce3cb581efe7e520fc4de2'

declare global {
  interface Window { _hmt?: Array<(string | boolean)[]> }
}

/**
 * 应用启动时调用。开启时动态注入 hm.js。
 * 注意：百度官方"代码检查"要求在网页源码里静态看到 hm.baidu.com/hm.js，
 * 动态注入可能无法通过自动检查，重新开启统计后如需验证请在
 * 百度统计后台用"手动检查"或临时把脚本写回 index.html。
 */
export function initAnalytics() {
  if (!BAIDU_ANALYTICS_ENABLED) return
  window._hmt = window._hmt || []
  const hm = document.createElement('script')
  hm.src = `https://hm.baidu.com/hm.js?${BAIDU_SITE_ID}`
  document.head.appendChild(hm)
}

/** SPA 路由变化时手动上报 PV（首次加载由 hm.js 自动统计，无需调用）。关闭时自动为空操作。 */
export function trackPageview(path: string) {
  window._hmt?.push(['_trackPageview', path])
}

/** 自定义事件：category 事件分类（后台一张表），action 动作，label 细分项。关闭时自动为空操作。 */
export function trackEvent(category: string, action: string, label?: string) {
  window._hmt?.push(['_trackEvent', category, action, label ?? ''])
}
