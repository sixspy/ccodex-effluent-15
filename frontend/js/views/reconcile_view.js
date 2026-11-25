export const reconcileViewTemplate = `
  <div class="grid-2">
    <div class="panel">
      <h3>许可对账</h3>
      <div class="actions"><button class="secondary" @click="loadReconcile">刷新全部</button></div>
      <table>
        <thead><tr><th>许可</th><th>对齐</th><th>证明</th><th>封批数</th></tr></thead>
        <tbody>
          <tr v-for="r in reconAllItems" :key="r.permit_code">
            <td>{{ r.permit_code }}</td>
            <td :class="r.balanced?'pass':'fail'">{{ r.balanced ? "齐" : "不齐" }}</td>
            <td :class="r.proof_ready?'pass':'warn'">{{ r.proof_ready ? "可证" : "未齐" }}</td>
            <td>{{ r.seal_count || 0 }}</td>
          </tr>
        </tbody>
      </table>
      <h3 style="margin-top:1rem">采样行 · 可重裁同态（驳回回写已裁定后该键删除）</h3>
      <table>
        <thead><tr><th>许可</th><th>采样</th><th>正式批态</th><th>可重裁</th></tr></thead>
        <tbody>
          <template v-for="r in reconAllItems" :key="r.permit_code">
            <tr v-for="s in r.samples" :key="r.permit_code + s.sample_code">
              <td>{{ r.permit_code }}</td>
              <td>{{ s.sample_code }}</td>
              <td :class="sampleClass(s.status)">{{ s.status }}</td>
              <td>
                <span v-if="s.can_re_adjudicate" class="warn">可重裁</span>
                <span v-else class="pass">—</span>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>
    <div class="panel">
      <h3>单许可 / 采样证明</h3>
      <label>许可号</label><input v-model="reconCode"/>
      <div class="actions"><button @click="loadReconcileOne">对账</button></div>
      <pre v-if="reconOne" style="white-space:pre-wrap;font-size:0.82rem">{{ JSON.stringify(reconOne, null, 2) }}</pre>
      <label>采样号证明</label><input v-model="proofCode"/>
      <div class="actions"><button class="secondary" @click="loadProof">证明</button></div>
      <pre v-if="proofOne" style="white-space:pre-wrap;font-size:0.82rem">{{ JSON.stringify(proofOne, null, 2) }}</pre>
    </div>
  </div>`;
