export const releaseViewTemplate = `
  <div class="grid-2">
    <div class="panel">
      <h3>准排放记录</h3>
      <table>
        <thead><tr><th>准排号</th><th>采样</th><th>口</th><th>值班</th><th>时间</th></tr></thead>
        <tbody>
          <tr v-for="r in releases" :key="r.id">
            <td>{{ r.release_ref }}</td><td>{{ r.sample_code }}</td><td>{{ r.outfall_code }}</td>
            <td>{{ r.officer }}</td><td>{{ r.released_at }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="panel">
      <h3>签发准排</h3>
      <label>已裁定采样（旁路挂起灰态不可选，驳回回写后自动解除）</label>
      <select v-model.number="releaseForm.sample_id">
        <option v-for="s in releasableSamples" :key="s.id" :value="s.id">{{ s.sample_code }} · {{ s.status }}</option>
      </select>
      <label>值班员</label><input v-model="releaseForm.officer"/>
      <div class="actions"><button @click="createRelease">准排</button></div>
      <div v-if="pendingSamples.length" class="panel" style="margin-top:0.8rem;border-style:dashed">
        <h3>旁路挂起 · 灰态（准排不可用 / 可重裁）</h3>
        <table>
          <thead><tr><th>采样</th><th>主批态</th><th>可重裁</th></tr></thead>
          <tbody>
            <tr v-for="s in pendingSamples" :key="s.id" class="muted">
              <td>{{ s.sample_code }}</td>
              <td :class="sampleClass(s.status)">{{ s.status }}</td>
              <td :class="s.can_re_adjudicate ? 'warn' : 'pass'">{{ s.can_re_adjudicate ? "可重裁" : "—" }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>`;
