export const exceedViewTemplate = `
  <div class="panel">
    <h3>超标旁路挂起 · 驳回回态</h3>
    <p class="muted">驳回（甲路径）：挂起关闭与主批态回写已裁定同事务，旁路标记同清；后到会话抢锁失败只记争用痕。</p>
    <table>
      <thead><tr><th>键</th><th>采样</th><th>指标</th><th>测值</th><th>限值</th><th>挂起态</th><th>主批态</th><th>可重裁</th><th></th></tr></thead>
      <tbody>
        <tr v-for="h in exceeds" :key="h.id">
          <td>{{ h.hold_key }}</td><td>{{ h.sample_code }}</td><td>{{ h.exceed_metric }}</td>
          <td>{{ h.measured }}</td><td>{{ h.limit_value }}</td>
          <td :class="h.status==='开放'?'fail':'pass'">{{ h.status }}</td>
          <td :class="sampleClass(mainStatusOf(h))">{{ mainStatusOf(h) }}</td>
          <td><span :class="canReAdjudicateOf(h)?'warn':'pass'">{{ canReAdjudicateOf(h) ? "可重裁" : "—" }}</span></td>
          <td>
            <button v-if="h.status==='开放'" class="secondary" style="width:auto;margin:0 0.3rem 0 0" @click="closeExceed(h.id)">闭环</button>
            <button v-if="h.status==='开放'" style="width:auto;margin:0" @click="rejectExceed(h.id)">驳回</button>
          </td>
        </tr>
      </tbody>
    </table>
  </div>`;
