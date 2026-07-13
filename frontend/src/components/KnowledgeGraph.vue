<script setup lang="ts">
import { computed, ref } from 'vue'
import { Back, Reading } from '@element-plus/icons-vue'
import type { Chapter } from '@/types'
import { formatTextbookParagraphs } from '@/utils/textbookText'

const props = defineProps<{ courseName: string; chapters: Chapter[] }>()
const emit = defineEmits<{ learn: [chapterId: number] }>()
const selectedId = ref<number | null>(null)
const selectedChapter = computed(() => props.chapters.find((item) => item.id === selectedId.value) || null)

function chapterDisplayTitle(chapter: Chapter): string {
  const title = chapter.title.trim()
  if (!/^第\s*[一二三四五六七八九十百0-9]+\s*章$/.test(title)) return title
  const content = formatTextbookParagraphs(chapter.content).join(' ')
  const quoted = content.match(/[“"《]([^”"》]{4,32})[”"》]/)?.[1]
  const opening = content
    .replace(/^《[^》]+》\s*/, '')
    .split(/[，。；：]/)
    .map((item) => item.trim())
    .find((item) => item.length >= 4)
  const topic = (quoted || opening || '').replace(/^(本章|本专题|主要内容是)/, '').trim()
  return topic ? `${title} ${topic.length > 22 ? `${topic.slice(0, 22)}…` : topic}` : title
}

const overviewNodes = computed(() => {
  const total = props.chapters.length
  const innerCount = total <= 8 ? total : Math.min(7, Math.ceil(total * .4))
  return props.chapters.map((chapter, index) => {
    const inner = index < innerCount
    const ringIndex = inner ? index : index - innerCount
    const ringCount = inner ? innerCount : total - innerCount
    const offset = inner ? -.32 : .18
    const angle = -Math.PI / 2 + offset + (Math.PI * 2 * ringIndex) / Math.max(ringCount, 1)
    return {
      chapter,
      title: chapterDisplayTitle(chapter),
      x: 50 + Math.cos(angle) * (inner ? 25 : 43),
      y: 50 + Math.sin(angle) * (inner ? 28 : 42),
      inner,
    }
  })
})

function extractKnowledgePoints(chapter: Chapter): string[] {
  const content = formatTextbookParagraphs(chapter.content).join('')
  const candidates = content
    .split(/[。！？；]/)
    .map((item) => item.replace(/^[“”"'（(一二三四五六七八九十、，\s]+/, '').trim())
    .filter((item) => item.length >= 6)
  const unique = [...new Set(candidates.map((item) => item.length > 24 ? `${item.slice(0, 24)}…` : item))]
  return unique.slice(0, 6).length ? unique.slice(0, 6) : [chapter.title]
}

const radialPoints = computed(() => {
  if (!selectedChapter.value) return []
  const points = extractKnowledgePoints(selectedChapter.value)
  return points.map((label, index) => {
    const angle = -Math.PI / 2 + (Math.PI * 2 * index) / points.length
    return {
      label,
      x: 50 + Math.cos(angle) * 35,
      y: 50 + Math.sin(angle) * 34,
    }
  })
})
</script>

<template>
  <section class="knowledge-graph-card">
    <header class="knowledge-graph-heading">
      <div><p class="eyebrow">Knowledge Map</p><h2>教材知识图谱</h2><p>{{ selectedChapter ? '查看当前专题的核心知识点' : '点击专题节点，展开本章知识结构' }}</p></div>
      <el-button v-if="selectedChapter" :icon="Back" plain @click="selectedId = null">返回全书</el-button>
    </header>

    <div class="knowledge-graph-stage">
      <div class="graph-stars"></div>
      <div v-if="!selectedChapter" class="knowledge-overview">
        <div class="orbit orbit-inner"></div><div class="orbit orbit-outer"></div>
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true"><line v-for="node in overviewNodes" :key="node.chapter.id" x1="50" y1="50" :x2="node.x" :y2="node.y" /></svg>
        <div class="course-knowledge-core"><span>教材知识体系</span><strong>{{ courseName }}</strong><small>{{ chapters.length }} 个专题</small></div>
        <button v-for="node in overviewNodes" :key="node.chapter.id" class="chapter-bubble" :class="{ inner: node.inner }" :style="{ left: `${node.x}%`, top: `${node.y}%` }" :title="node.title" @click="selectedId = node.chapter.id">
          <strong>{{ String(node.chapter.sort_order || node.chapter.id).padStart(2, '0') }}</strong>
          <span>{{ node.title }}</span>
        </button>
      </div>

      <div v-else class="knowledge-radial">
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
          <line v-for="point in radialPoints" :key="point.label" x1="50" y1="50" :x2="point.x" :y2="point.y" />
        </svg>
        <button class="knowledge-core" @click="emit('learn', selectedChapter.id)"><strong>{{ chapterDisplayTitle(selectedChapter) }}</strong><span>进入学习</span></button>
        <button v-for="(point, index) in radialPoints" :key="`${point.label}-${index}`" class="knowledge-node" :style="{ left: `${point.x}%`, top: `${point.y}%` }" :title="point.label" @click="emit('learn', selectedChapter.id)"><span>{{ point.label }}</span></button>
      </div>
    </div>
    <footer class="knowledge-graph-footer"><span><el-icon><Reading /></el-icon>{{ chapters.length }} 个专题</span><span>专题 → 知识点 → 阶段学习</span></footer>
  </section>
</template>
