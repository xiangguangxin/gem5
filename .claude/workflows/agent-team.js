// Host contract: args object, async agent(prompt, options), log(message).
// This is a workflow-host script, not a standalone Node CLI. See ../references/team-contract.md.
export const meta = {
  name: 'agent-team',
  description: '顺序交接的团队流程；空结果、未通过评审和无证据验证均不放行',
  phases: [{title:'设计'}, {title:'文档'}, {title:'实现'}, {title:'验证'}],
}

const REVIEW_SCHEMA = {
  type:'object',
  properties:{
    verdict:{type:'string', enum:['approve','needs_fix']},
    findings:{type:'array', items:{type:'object', properties:{
      severity:{type:'string', enum:['P0','P1','P2','P3']},
      issue:{type:'string'}, trigger:{type:'string'}, suggestion:{type:'string'},
      location:{type:'string'}, evidence:{type:'string'},
    }, required:['severity','issue','trigger','suggestion']}},
  }, required:['verdict','findings'],
}
const VERIFY_SCHEMA = {
  type:'object', properties:{
    verdict:{type:'string', enum:['pass','fail']}, evidence:{type:'string'},
    issues:{type:'array', items:{type:'string'}},
  }, required:['verdict','evidence','issues'],
}
const MAX_ROUNDS = 3
const input = typeof args === 'object' && args ? args : {}
const requirement = typeof input.requirement === 'string' ? input.requirement.trim() : ''
let architecture = null, design = null, code = null, verification = null
const history = []
const finish = (done, status, reason) => ({requirement, architecture, design, code,
  verification, history, done, status, reason})
if (!requirement) return finish(false, 'invalid_input', '缺少具体 requirement，不派发任务')
if (typeof agent !== 'function' || typeof log !== 'function') {
  throw new Error('Workflow host must supply agent() and log()')
}
const context = JSON.stringify({requirement, scope:input.scope || [],
  acceptance:input.acceptance || [], constraints:input.constraints || []}, null, 2)
const dispatch = async (role, phase, task, schema) => {
  const prompt = `原始任务与边界（每轮保留）：\n${context}\n\n${task}\n\n遵循 .claude/references/team-contract.md；工具可用性与用户授权由宿主执行。不要自行提交推送。`
  return await agent(prompt, {label:`${role}: ${phase}`, phase, agentType:role, ...(schema ? {schema} : {})})
}
const artifact = x => typeof x === 'string' ? x.trim().length > 0
  : !!x && typeof x === 'object' && Object.keys(x).length > 0
const findingsText = fs => fs.map(f => JSON.stringify(f)).join('\n')
function reviewError(r) {
  if (!r || !['approve','needs_fix'].includes(r.verdict) || !Array.isArray(r.findings)) return '评审结果缺失或格式无效'
  if (r.findings.some(f => !f || !['P0','P1','P2','P3'].includes(f.severity)
      || ['issue','trigger','suggestion'].some(k => typeof f[k] !== 'string' || !f[k].trim()))) return '缺陷记录无效'
  if (r.verdict === 'needs_fix' && !r.findings.length) return '要求修复但没有具体问题'
  if (r.verdict === 'approve' && r.findings.some(f => ['P0','P1'].includes(f.severity))) return '评审声称通过但仍有阻断缺陷'
  return null
}
try {
  architecture = await dispatch('cto','设计','给出需求理解、验收映射、备选与推荐、文件范围、风险和可执行任务。缺少关键决定时明确标出，不虚构批准。')
  if (!artifact(architecture)) return finish(false,'invalid_result','架构产物为空')
  let archOk = false
  for (let round=0; round<MAX_ROUNDS; round++) {
    const r = await dispatch('red-team','设计',`评审架构：\n${JSON.stringify(architecture)}\n输出 approve 或 needs_fix；允许无缺陷，不为反对而反对。`,REVIEW_SCHEMA)
    const error = reviewError(r)
    history.push({phase:'design_review',round:round+1,result:r})
    if (error) return finish(false,'invalid_result',error)
    if (r.verdict === 'approve') { archOk=true; break }
    if (round+1 < MAX_ROUNDS) {
      architecture = await dispatch('cto','设计',`修订原方案并逐条说明处理：\n${JSON.stringify(architecture)}\n缺陷：\n${findingsText(r.findings)}`)
      if (!artifact(architecture)) return finish(false,'invalid_result','修订架构为空')
    }
  }
  if (!archOk) return finish(false,'needs_revision','架构评审达到轮数上限，不进入实现')
  design = await dispatch('tech-writer','文档',`把已评审方案整理为足够实施的文档，沿用指定路径，不要求机械新增 docs 文件：\n${JSON.stringify(architecture)}`)
  if (!artifact(design)) return finish(false,'invalid_result','设计文档产物为空')
  let feedback = ''
  for (let round=0; round<MAX_ROUNDS; round++) {
    code = await dispatch('developer','实现',`按设计完成任务，返回文件清单、行为和验证记录。按改动选择必要测试，不为纯文档制造单测。\n设计：${JSON.stringify(design)}\n上一轮完整反馈：${feedback}`)
    if (!artifact(code)) return finish(false,'invalid_result','实现产物为空')
    const review = await dispatch('red-team','实现',`基于实际文件/diff 复查实现，不只信开发者摘要：\n${JSON.stringify(code)}\n设计：${JSON.stringify(design)}`,REVIEW_SCHEMA)
    const error = reviewError(review)
    history.push({phase:'implementation_review',round:round+1,result:review})
    if (error) return finish(false,'invalid_result',error)
    if (review.verdict === 'needs_fix') { feedback=findingsText(review.findings); continue }
    verification = await dispatch('verifier','验证',`按原始验收独立检查实际产物，选择与改动相关的验证；列命令、退出码、关键输出、未运行项及理由。缺工具或测试失败不能伪造通过。\n设计：${JSON.stringify(design)}\n实现：${JSON.stringify(code)}\n评审：${JSON.stringify(review)}`,VERIFY_SCHEMA)
    history.push({phase:'verification',round:round+1,result:verification})
    if (!verification || !['pass','fail'].includes(verification.verdict)
        || typeof verification.evidence !== 'string' || !verification.evidence.trim()
        || !Array.isArray(verification.issues) || verification.issues.some(x => typeof x !== 'string')) {
      return finish(false,'invalid_result','验证结果缺失、无证据或格式无效')
    }
    if (verification.verdict === 'pass' && verification.issues.length === 0) {
      log('验证报告通过；请依据命令与输出核对证据。未自动提交、合并或推送。')
      return finish(true,'verified','已通过本次验收与评审')
    }
    feedback = JSON.stringify(verification)
  }
  return finish(false,'needs_revision','实现或验证达到轮数上限；保留问题及证据，停止自动回环')
} catch (error) {
  log(`团队流程停止：${String(error)}`)
  return finish(false,'execution_error',String(error))
}
