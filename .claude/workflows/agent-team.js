export const meta = {
  name: 'agent-team',
  description: '用 cto / red-team / tech-writer / developer / verifier 团队开发，对抗评审与验证门禁硬性内置',
  phases: [
    { title: '设计' },
    { title: '文档' },
    { title: '实现' },
    { title: '验证' },
  ],
}

// 结构化输出，用于驱动闸门回环（机器可读的 verdict）
const REVIEW_SCHEMA = {
  type: 'object',
  properties: {
    verdict: { type: 'string', enum: ['approve', 'needs_fix'] },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          severity: { type: 'string' },
          issue: { type: 'string' },
          trigger: { type: 'string' },
          suggestion: { type: 'string' },
        },
        required: ['severity', 'issue'],
      },
    },
  },
  required: ['verdict', 'findings'],
}

const VERIFY_SCHEMA = {
  type: 'object',
  properties: {
    verdict: { type: 'string', enum: ['pass', 'fail'] },
    evidence: { type: 'string' },
    issues: { type: 'array', items: { type: 'string' } },
  },
  required: ['verdict', 'evidence'],
}

const MAX_ROUNDS = 3
const requirement = (args && args.requirement) || '（未指定需求）'
const findingsText = (fs) => (fs || []).map((f) => `${f.severity || '?'}: ${f.issue}`).join('\n')

// ── 设计：cto → red-team 闸门（不过就回 cto 修订） ──
let architecture = await agent(
  `分析需求并产出架构方案 + 任务清单（含约束、待决策、风险）：\n${requirement}`,
  { label: 'cto: 架构方案', phase: '设计', agentType: 'cto' }
)

let archOk = false
for (let i = 0; i < MAX_ROUNDS && !archOk; i++) {
  const review = await agent(
    `对抗评审下面这份架构方案，找缺陷与失败模式。\n\n${architecture}\n\n评审结论：verdict=approve（无显著缺陷）或 needs_fix（有必须修复的缺陷）。`,
    { label: `red-team: 攻架构 #${i + 1}`, phase: '设计', agentType: 'red-team', schema: REVIEW_SCHEMA }
  )
  if (!review || review.verdict === 'approve') {
    archOk = true
    log('✅ 架构评审通过')
  } else {
    log(`❌ 架构评审不通过（第 ${i + 1} 轮）：\n${findingsText(review.findings)}`)
    architecture = await agent(
      `按评审意见修订架构方案，逐条回应缺陷：\n\n缺陷清单：\n${findingsText(review.findings)}\n\n原方案：\n${architecture}`,
      { label: 'cto: 修订架构', phase: '设计', agentType: 'cto' }
    )
  }
}

// ── 文档 ──
const design = await agent(
  `把下面这份架构方案写成设计文档，接口必须具体到可编码：\n\n${architecture}`,
  { label: 'tech-writer: 设计文档', phase: '文档', agentType: 'tech-writer' }
)

// ── 实现 + 验证：developer → red-team 闸门 → verifier 门禁（失败回环，反馈回灌） ──
let code = null
let feedback = ''
let done = false
for (let round = 0; round < MAX_ROUNDS && !done; round++) {
  const feedbackNote = feedback ? `\n\n上一轮评审的缺陷清单（必须修复）：\n${feedback}` : ''
  code = await agent(
    `按设计文档实现代码 + 单测（TDD），小步提交：\n\n${design}${feedbackNote}`,
    { label: `developer: 实现 #${round + 1}`, phase: '实现', agentType: 'developer' }
  )

  const codeReview = await agent(
    `对抗评审下面这份实现，找缺陷与失败模式。\n\n${code}\n\n评审结论：verdict=approve 或 needs_fix。`,
    { label: `red-team: 攻代码 #${round + 1}`, phase: '实现', agentType: 'red-team', schema: REVIEW_SCHEMA }
  )
  if (codeReview && codeReview.verdict === 'needs_fix') {
    feedback = findingsText(codeReview.findings)
    log(`❌ 代码评审不通过（第 ${round + 1} 轮）：\n${feedback}`)
    continue
  }

  const verify = await agent(
    `实际运行 build/测试并评审下面这份代码，产出带真实输出的验证报告。\n\n设计：\n${design}\n\n代码：\n${code}\n\n结论：verdict=pass（build+测试通过）或 fail（列出问题清单）。`,
    { label: `verifier: 验证 #${round + 1}`, phase: '验证', agentType: 'verifier', schema: VERIFY_SCHEMA }
  )
  if (verify && verify.verdict === 'pass') {
    done = true
    log(`✅ 验证通过。证据：\n${verify.evidence}`)
  } else {
    feedback = ((verify && verify.issues) || ['验证失败，无问题清单']).join('\n')
    log(`❌ 验证不通过（第 ${round + 1} 轮）：\n${feedback}`)
  }
}

if (!done) {
  log(`⚠️ 达到最大轮次 ${MAX_ROUNDS}，仍未通过，停止并交人工处理。`)
}

return { requirement, architecture, design, code, done }
