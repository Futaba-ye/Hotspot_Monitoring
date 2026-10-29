import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from './App.jsx'

let rules
let events
let notifications
let requests

function response(value, status = 200) {
  return { ok: status < 400, status, json: async () => value }
}

beforeEach(() => {
  rules = []
  events = []
  notifications = []
  requests = []
  vi.stubGlobal('fetch', vi.fn(async (url, options = {}) => {
    const path = url.replace('/api', '')
    const method = options.method || 'GET'
    requests.push({ path, method, body: options.body })
    if (path === '/status') return response({
      rules: rules.filter((rule) => rule.enabled).length,
      events: events.length,
      unread: notifications.filter((item) => !item.read_at).length,
      ai_configured: true, x_configured: true, email_configured: true,
      model: 'nvidia/nemotron-3.5-super-vl:free', sources: [],
    })
    if (path === '/rules' && method === 'GET') return response(rules)
    if (path === '/events') return response(events)
    if (path === '/notifications') return response(notifications)
    if (path === '/rules' && method === 'POST') {
      const body = JSON.parse(options.body)
      const rule = { ...body, id: 1, enabled: 1, created_at: new Date().toISOString(), last_run_at: null, last_error: null }
      rules = [rule]
      return response(rule, 201)
    }
    if (path.match(/^\/notifications\/\d+\/read$/) && method === 'POST') {
      notifications = notifications.map((item) => ({ ...item, read_at: new Date().toISOString() }))
      return response({ ok: true })
    }
    return response({ detail: '未知接口' }, 404)
  }))
})

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

test('可以从页面创建关键词监控', async () => {
  const user = userEvent.setup()
  render(<App />)
  await screen.findByRole('heading', { name: /追踪变化/ })
  await user.click(screen.getByRole('button', { name: /建立你的监控/ }))
  await user.type(screen.getByLabelText('监控内容'), 'GPT-6 发布')
  await user.click(screen.getByRole('button', { name: /开始监控/ }))
  await waitFor(() => expect(rules).toHaveLength(1))
  expect(rules[0].query).toBe('GPT-6 发布')
  expect(rules[0].kind).toBe('keyword')
  expect(screen.getByRole('heading', { name: 'GPT-6 发布' })).toBeTruthy()
})

test('事件能展开原始证据', async () => {
  const user = userEvent.setup()
  events = [{
    id: 7, rule_id: 1, rule_query: 'AI 编程', rule_kind: 'topic',
    title: '编程助手更新', summary: '一个编程助手推出新版本。', reason: '有官方公告。',
    status: 'verified', heat: 80, updated_at: new Date().toISOString(),
    evidence: [{ source: '官方 RSS · openai.com', source_url: 'https://openai.com/news/example', title: '原始公告' }],
  }]
  render(<App />)
  await screen.findByRole('heading', { name: '编程助手更新' })
  await user.click(screen.getByRole('button', { name: /查看证据/ }))
  expect(screen.getByText('有官方公告。')).toBeTruthy()
  expect(screen.getByRole('link', { name: /原始公告/ }).getAttribute('href')).toBe('https://openai.com/news/example')
})

test('提醒收件箱可以标记已读', async () => {
  const user = userEvent.setup()
  notifications = [{
    id: 9, event_id: 7, title: '新模型发布', summary: '已核实的更新。',
    created_at: new Date().toISOString(), read_at: null, email_status: '已发送',
  }]
  render(<App />)
  await screen.findByRole('heading', { name: /追踪变化/ })
  await user.click(screen.getByRole('button', { name: /提醒收件箱/ }))
  await user.click(screen.getByRole('button', { name: '标记已读' }))
  await waitFor(() => expect(requests.some((item) => item.path === '/notifications/9/read' && item.method === 'POST')).toBe(true))
  await screen.findByText(/已读 ·/)
})
