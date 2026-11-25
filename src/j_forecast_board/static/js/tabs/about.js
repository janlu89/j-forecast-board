// SPDX-License-Identifier: Apache-2.0
import { api } from "../core/api.js";
import { $, esc } from "../core/dom.js";

export async function renderAbout() {
  let sys = {};
  try { sys = await api("api/system"); } catch (e) { /* optional */ }
  const repo = "https://github.com/janlu89/j-forecast-board";
  $("#aboutBody").innerHTML = `
  <h2>J-Forecast Board</h2>
  <p class="lead"><b>J-Forecast Board</b> by <b>Gianluca Meola</b> · version ${esc(sys.version || "?")} · licence
  <a href="${repo}/blob/main/LICENSE" target="_blank" rel="noopener">Apache-2.0</a> ·
  <a href="${repo}" target="_blank" rel="noopener">${repo.replace("https://", "")}</a></p>
  <p>A local workbench to test time-series forecasting on public data and on your own, powered by <b>Timestral</b>, the open
  time-series foundation model by Mistral AI. Timestral forecasts any series <b>zero-shot</b> (no training on your data) and returns a
  full probability distribution (21 quantiles), not just one number. Everything runs on this PC's CPU: no GPU, no account, and your
  data stays here unless you connect an external AI assistant yourself.</p>
  <p class="note">An independent project: not affiliated with, endorsed by or supported by Mistral AI.</p>
  <h2>The tabs</h2>
  <ul>
    <li><b>Overview</b> – the analysis page: summary, headline numbers, leaderboard vs classic methods, error by step / weekday / group, calibration, best &amp; worst series.</li>
    <li><b>Series</b> – one series with holdout (orange), future (green) and the covariates underneath.</li>
    <li><b>Total</b> – the sum of all series: bottom-up vs forecasting the total directly.</li>
    <li><b>Explore backtest</b> – move “today” through history and watch the forecast adapt; later data is hidden.</li>
    <li><b>Live forecast</b> – forecast from any date and horizon on the spot.</li>
    <li><b>Split test</b> – give the model only part of the history (e.g. 2 of 5 years) and see how it forecasts the rest, period by period, against simple rules.</li>
    <li><b>What-if</b> – edit future covariates (promotions, opening days, weather…) and see the effect.</li>
    <li><b>Anomalies</b> – points outside the model’s uncertainty band.</li>
    <li><b>Order planner</b> – turn the forecast quantiles into how much to stock, and compare lost sales vs leftover stock (and their cost) with a classic “forecast + safety buffer”.</li>
    <li><b>💬 Ask about this page</b> (button at the bottom right, optional) – an AI assistant you choose (a model on this PC, an online
      API, or the Claude Code CLI) explains what is on screen and can run the app's forecasting tools. It is off until you set it up, and
      it tells you plainly when your questions leave this PC.</li>
    <li><b>Your data</b> – load a CSV with one or many series (e.g. all your stores).</li>
  </ul>
  <h2>How the evaluation works</h2>
  <p>For each series the last <i>horizon</i> points (several windows for single series) are hidden, forecast blind, and compared with reality.
  The same is done with classic baselines (repeat last week, same day last year, average by weekday × promotion, …).
  Results are computed once in the background and cached in the app's data folder, so the pages open instantly.</p>
  <h2>How to read the numbers</h2>
  <ul>
    <li><b>MAPE</b> – average % error per point (e.g. per store and day). <b>RMSPE</b> – the Kaggle Rossmann metric, punishes big misses.</li>
    <li><b>WAPE</b> – total absolute error / total volume: the business view. <b>sMAPE</b> – symmetric % error.</li>
    <li><b>MASE</b> – error relative to the “repeat last season” rule: <b>below 1 = better</b>.</li>
    <li><b>Bias</b> – positive = over-forecasting, negative = under-forecasting.</li>
    <li><b>WQL</b> – weighted quantile loss: scores the whole uncertainty band. <b>Cov. 80%</b> – share of real values inside the 10–90% band (≈80% = honest).
    <b>Width 80%</b> – how wide that band is relative to the volume.</li>
  </ul>
  <h2>Data &amp; licences</h2>
  <ul>
    <li><b>This app</b>: Apache-2.0. If you redistribute it or build on it, keep the copyright and the NOTICE file.</li>
    <li><b>Timestral weights</b>: Mistral's “Modified MIT” licence. Free, <b>except for companies (and their employees) with consolidated
      revenue above 20 M$ per month</b>: they need a commercial licence from Mistral. The weights are downloaded from Hugging Face by you;
      they are not part of this app.</li>
    <li><b>Rossmann</b>: Kaggle competition data (2015), read from a public GitHub mirror. Check Kaggle's rules before any other use.</li>
    <li><b>Your data</b>: kept in this app's memory only, never sent to an external AI assistant.</li>
  </ul>
  <h2>Credits</h2>
  <ul>
    <li>Mistral AI for Timestral: <a href="https://mistral.ai/news/timestral/" target="_blank" rel="noopener">announcement</a>,
      <a href="https://github.com/mistralai/timestral" target="_blank" rel="noopener">code</a>,
      <a href="https://huggingface.co/mistralai" target="_blank" rel="noopener">models on Hugging Face</a>.</li>
    <li>Thanks to <a href="https://github.com/simone-rizzo" target="_blank" rel="noopener">Simone Rizzo</a> for sharing the idea that sparked
      this project. He is not involved in it and has not reviewed or endorsed it.</li>
    <li><a href="https://plotly.com/javascript/" target="_blank" rel="noopener">Plotly.js</a> (MIT) for the charts; the public datasets'
      authors (UCI, ETDataset, Open Power System Data, Box &amp; Jenkins, Australian Bureau of Meteorology).</li>
    <li>Built with <a href="https://claude.com/claude-code" target="_blank" rel="noopener">Claude Code</a>.</li>
  </ul>
  <h2>This machine</h2>
  <p class="note">${esc(sys.os || "")} · ${esc(sys.cpu || "")} · ${sys.cores || "?"} logical cores · Python ${esc(sys.python || "")} · torch ${esc(sys.torch || "")} (CPU only) · model: ${esc(sys.model_backend || "")}${sys.offline ? " · offline" : ""}</p>`;
}
