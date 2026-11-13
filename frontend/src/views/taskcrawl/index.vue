<template>
  <section class="page" data-module="taskcrawl">
    <header class="page-head">
      <div>
        <h2>采集任务管理</h2>
        <p class="page-desc">定义单次或周期性采集任务，关联采集源与解析规则，记录增量水位与批次边界。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记采集任务</button>
        <button class="btn" type="button" @click="exportRows">导出采集任务清单</button>
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
          <th>准入结论</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :class="{ 'row-selected': selected?.id === row.id }">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td>
            <span v-if="row.admission?.allowed" class="state-ok">通过</span>
            <span v-else class="state-blocked">未通过</span>
            <div v-if="row.admission?.reason" class="admission-reason">{{ row.admission.reason }}</div>
          </td>
          <td class="row-actions">
            <span v-if="!row.status" class="muted-text">状态缺失</span>
            <span v-else-if="!allowedActions(row).length" class="muted-text">{{ row.status }}，无后续动作</span>
            <button
              v-for="action in allowedActions(row)"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
            <button class="link" type="button" @click="showDetail(row)">详情</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无采集任务数据，可先登记采集任务</td>
        </tr>
      </tbody>
    </table>

    <section v-if="selected" class="detail-panel">
      <header class="detail-head">
        <h3>{{ selected['任务编号'] }} · 任务详情</h3>
        <button class="btn ghost" type="button" @click="selected = null">收起</button>
      </header>
      <p class="detail-line">
        当前状态：<strong>{{ selected.status }}</strong>
        <span v-if="selected.admission?.allowed" class="state-ok"> · 准入通过</span>
        <span v-else class="state-blocked"> · 准入未通过</span>
      </p>
      <p v-if="selected.admission?.reason" class="detail-line state-blocked">{{ selected.admission.reason }}</p>
      <table v-if="selected.admission?.config" class="data-table detail-table">
        <thead>
          <tr>
            <th>配置项</th>
            <th>采集源</th>
            <th>解析规则</th>
            <th>调度批次</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>生效值</td>
            <td>
              <div v-for="(value, key) in selected.admission.config['采集源']" :key="`s-${key}`">
                {{ key }}：{{ value || '—' }}
              </div>
            </td>
            <td>
              <div v-for="(value, key) in selected.admission.config['解析规则']" :key="`r-${key}`">
                {{ key }}：{{ value || '—' }}
              </div>
            </td>
            <td>
              <div v-for="(value, key) in selected.admission.config['调度配置']" :key="`t-${key}`">
                {{ key }}：{{ value || '—' }}
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <footer class="page-foot">
      <span>共 {{ total }} 条采集任务记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Admission = {
  allowed: boolean
  reason: string
  datasource_status: string | null
  rule_status: string | null
  config: Record<string, Record<string, string>>
}

type Row = {
  id: number
  status?: string
  admission?: Admission
} & Record<string, string | number | null>

const ENDPOINT = '/api/taskcrawl'
const columns = ["任务编号", "采集源名称", "规则编号", "调度周期", "增量字段", "批次大小", "起始水位", "截止水位"]
// 状态序列与服务层一致：启动任务只能从「待调度」进入。
const STATUS_ORDER = ['草稿', '待调度', '执行中', '已完成', '已终止']
const ACTIONS = ['提交调度', '启动任务', '终止任务']
const stats = [{"label": "采集任务总数", "value": 0}, {"label": "执行中任务", "value": 0}, {"label": "已完成任务", "value": 0}]

const rows = ref<Row[]>([])
const total = ref(0)
const selected = ref<Row | null>(null)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

function actionTarget(action: string): string | null {
  if (action === '提交调度') return '待调度'
  if (action === '启动任务') return '执行中'
  if (action === '终止任务') return '已终止'
  return null
}

/** 当前状态可执行的动作：只允许推进到严格后继；已完成是终态，不展示动作。 */
function allowedActions(row: Row): string[] {
  const current = STATUS_ORDER.indexOf(String(row.status ?? ''))
  if (current < 0) return []
  return ACTIONS.filter((action) => {
    const target = actionTarget(action)
    // 「终止任务」可作用于草稿、待调度和执行中，其余动作只能推进一格。
    if (target === '已终止') {
      return ['草稿', '待调度', '执行中'].includes(String(row.status ?? ''))
    }
    return target !== null && STATUS_ORDER.indexOf(target) === current + 1
  })
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '采集任务登记入口尚未接入审批流'
}

function showDetail(row: Row) {
  selected.value = row
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    // 以服务端 { ok, message } 为准：准入不通过时后端没有落库，页面不得显示成功。
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      errorMessage.value = payload?.message ?? '采集任务动作未生效，请稍后重试'
      if (payload?.entry) {
        selected.value = payload.entry as Row
      }
      await reload()
      return
    }
    selected.value = payload.entry ? (payload.entry as Row) : null
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '采集任务操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('采集任务列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    if (selected.value) {
      const refreshed = rows.value.find((row) => row.id === selected.value?.id)
      selected.value = refreshed ?? null
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '采集任务列表读取失败'
  }
}

onMounted(reload)
</script>
