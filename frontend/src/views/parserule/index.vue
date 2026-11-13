<template>
  <section class="page" data-module="parserule">
    <header class="page-head">
      <div>
        <h2>解析规则管理</h2>
        <p class="page-desc">定义网页内容的解析提取规则，包括选择器表达式、容错处理和字段映射，为准确抽取提供结构化配置。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记解析规则</button>
        <button class="btn" type="button" @click="exportRows">导出解析规则清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <span v-if="!row.status" class="muted-text">状态缺失</span>
            <span v-else-if="!allowedActions(row).length" class="muted-text">已废弃，不可再流转</span>
            <button
              v-for="action in allowedActions(row)"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无解析规则数据，可先登记解析规则</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条解析规则记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/parserule'
const columns = ["规则编号", "页面选择器", "内容选择器", "属性提取器", "列表容错", "空值占位符", "字符清洗正则", "输出字段映射"]
// 状态序列与服务层一致：启用规则只能从「规则验证中」进入，草稿不会出现启用按钮。
const STATUS_ORDER = ['草稿', '规则验证中', '已启用', '已废弃']
const ACTIONS = ['提交规则验证', '启用规则', '废弃规则']
const stats = [{"label": "解析规则总数", "value": 0}, {"label": "已启用规则", "value": 0}, {"label": "验证中规则", "value": 0}]

function actionTarget(action: string): string | null {
  if (action === '提交规则验证') return '规则验证中'
  if (action === '启用规则') return '已启用'
  if (action === '废弃规则') return '已废弃'
  return null
}

/** 当前状态可执行的动作：只允许推进到严格后继；已废弃为终态，不展示任何动作。 */
function allowedActions(row: Row): string[] {
  const current = STATUS_ORDER.indexOf(String(row.status ?? ''))
  if (current < 0) return []
  return ACTIONS.filter((action) => {
    const target = actionTarget(action)
    return target !== null && STATUS_ORDER.indexOf(target) === current + 1
  })
}

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '解析规则登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      errorMessage.value = payload?.message ?? '解析规则动作未生效，请稍后重试'
      await reload()
      return
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '解析规则操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('解析规则列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '解析规则列表读取失败'
  }
}

onMounted(reload)
</script>
