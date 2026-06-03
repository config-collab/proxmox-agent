/**
 * Proxmox Agent GUI Enhancements
 *
 * Improvements #2-5:
 * 2. Risk-aware approval UI
 * 3. Feedback collection
 * 4. Weekly insights dashboard
 * 5. Community knowledge search
 *
 * Inject these into assistant.js for interactive features.
 */

// ─── Improvement #2: Risk Classification & Approval Modal ───────────────────

class RiskClassifier {
  static classify(toolName, operation) {
    const risks = {
      // Low-risk read-only operations
      "get_inventory": { level: "low", label: "Read-Only", reversible: true, time: "N/A", scope: "Information only", confidence: 100 },
      "get_metrics": { level: "low", label: "Read-Only", reversible: true, time: "N/A", scope: "Information only", confidence: 100 },
      "check_patches": { level: "low", label: "Read-Only", reversible: true, time: "N/A", scope: "Information only", confidence: 100 },

      // Low-risk config changes
      "pbs.fix.gc_permissions": {
        level: "low",
        label: "Config Change (Reversible)",
        reversible: true,
        time: "30 seconds",
        scope: "PBS only (no VMs affected)",
        confidence: 95,
        rollback: [
          "cp /etc/proxmox-backup/datastore.cfg.bak /etc/proxmox-backup/datastore.cfg",
          "systemctl restart proxmox-backup"
        ]
      },

      // Medium-risk operations
      "apply_patches": {
        level: "medium",
        label: "Package Updates",
        reversible: true,
        time: "5-10 minutes",
        scope: "Affects 1-3 guests",
        confidence: 87,
        rollback: [
          "apt-get install package=old-version (if available)",
          "Restore from backup if major breakage"
        ]
      },

      // High-risk irreversible
      "delete_vm": {
        level: "high",
        label: "DESTRUCTIVE - Data Loss Possible",
        reversible: false,
        time: "Permanent",
        scope: "VM and all data",
        confidence: 0,
        rollback: ["Restore from backup only"]
      },
    };

    return risks[toolName] || {
      level: "unknown",
      label: "Unknown Risk",
      reversible: true,
      time: "Unknown",
      scope: "Unknown",
      confidence: 50,
      rollback: ["Unknown rollback steps"]
    };
  }
}

// Show approval modal with risk context
function showApprovalModal(toolName, dryRun, operation) {
  const risk = RiskClassifier.classify(toolName, operation);

  const riskColors = {
    "low": "#4CAF50",
    "medium": "#FF9800",
    "high": "#F44336",
    "unknown": "#9E9E9E"
  };

  const riskEmoji = {
    "low": "🟢",
    "medium": "🟡",
    "high": "🔴",
    "unknown": "❓"
  };

  const modal = document.createElement("div");
  modal.className = "approval-modal";
  modal.style.cssText = `
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: rgba(0,0,0,0.7);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1000;
  `;

  modal.innerHTML = `
    <div class="modal-content" style="
      background: white;
      border-radius: 8px;
      padding: 24px;
      max-width: 600px;
      max-height: 80vh;
      overflow-y: auto;
      box-shadow: 0 4px 20px rgba(0,0,0,0.3);
    ">
      <h2>Approve Operation</h2>

      <div class="risk-badge" style="
        background: ${riskColors[risk.level]};
        color: white;
        padding: 12px 16px;
        border-radius: 6px;
        margin: 16px 0;
        font-size: 16px;
        font-weight: bold;
      ">
        ${riskEmoji[risk.level]} ${risk.label}
      </div>

      <section style="margin: 20px 0;">
        <h3>What Will Change</h3>
        <pre style="
          background: #f5f5f5;
          padding: 12px;
          border-radius: 4px;
          overflow-x: auto;
          font-size: 12px;
        ">${escapeHtml(dryRun)}</pre>
      </section>

      <section style="margin: 20px 0;">
        <h3>Risk Assessment</h3>
        <table style="width: 100%; border-collapse: collapse;">
          <tr style="border-bottom: 1px solid #ddd;">
            <td style="padding: 8px; font-weight: bold;">Reversible:</td>
            <td style="padding: 8px;">
              ${risk.reversible ? '✅ Yes' : '❌ NO'}
              (${risk.time})
            </td>
          </tr>
          <tr style="border-bottom: 1px solid #ddd;">
            <td style="padding: 8px; font-weight: bold;">Impact Scope:</td>
            <td style="padding: 8px;">${risk.scope}</td>
          </tr>
          <tr>
            <td style="padding: 8px; font-weight: bold;">Agent Confidence:</td>
            <td style="padding: 8px;">
              <div style="background: #e0e0e0; width: 200px; height: 20px; border-radius: 3px; overflow: hidden;">
                <div style="background: ${riskColors[risk.level]}; width: ${risk.confidence}%; height: 100%; transition: width 0.3s;"></div>
              </div>
              ${risk.confidence}%
            </td>
          </tr>
        </table>
      </section>

      ${risk.reversible ? `
      <section style="margin: 20px 0;">
        <h3>If This Goes Wrong (Rollback Steps)</h3>
        <ol style="margin: 8px 0; padding-left: 20px;">
          ${risk.rollback.map(step => `<li>${step}</li>`).join('')}
        </ol>
      </section>
      ` : `
      <section style="margin: 20px 0; padding: 12px; background: #ffebee; border-radius: 4px; border-left: 4px solid #f44336;">
        <strong>⚠️ WARNING: This operation is NOT reversible.</strong>
        <p>Once executed, there is no automatic rollback. Proceed only if you understand the consequences.</p>
      </section>
      `}

      <div style="margin-top: 24px; display: flex; gap: 8px; justify-content: flex-end;">
        <button onclick="cancelApproval()" style="
          padding: 10px 20px;
          background: #f5f5f5;
          border: 1px solid #ddd;
          border-radius: 4px;
          cursor: pointer;
        ">❌ Cancel</button>

        <button onclick="dryRunOnly()" style="
          padding: 10px 20px;
          background: #2196F3;
          color: white;
          border: none;
          border-radius: 4px;
          cursor: pointer;
        ">👁️ Review Only</button>

        <button onclick="approveOperation('${toolName}')" style="
          padding: 10px 20px;
          background: ${riskColors[risk.level]};
          color: white;
          border: none;
          border-radius: 4px;
          cursor: pointer;
          font-weight: bold;
        ">✅ Approve & Execute</button>
      </div>
    </div>
  `;

  document.body.appendChild(modal);
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function cancelApproval() {
  document.querySelector(".approval-modal").remove();
}

function dryRunOnly() {
  alert("Dry-run shown. No changes made.");
  cancelApproval();
}

function approveOperation(toolName) {
  // Send approval to server
  fetch('/api/execute', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({tool: toolName, apply: true})
  }).then(r => r.json()).then(data => {
    if (data.ok) {
      addMessage("Assistant", "✅ Operation approved and executing...");
    }
  });
  cancelApproval();
}

// ─── Improvement #3: Feedback Collection ───────────────────────────────────

function showFeedbackPrompt(toolName, result) {
  const feedback = document.createElement('div');
  feedback.className = 'feedback-card';
  feedback.id = `feedback-${toolName}`;
  feedback.style.cssText = `
    background: #f9f9f9;
    border: 1px solid #ddd;
    border-radius: 6px;
    padding: 12px;
    margin-top: 12px;
  `;

  feedback.innerHTML = `
    <div>
      <p style="margin: 0 0 8px 0;"><strong>Was this helpful?</strong></p>
      <div class="rating" style="display: flex; gap: 4px; margin-bottom: 8px;">
        ${[1,2,3,4,5].map(star => `
          <button onclick="rateTool('${toolName}', ${star})"
                  class="star"
                  data-value="${star}"
                  style="
                    background: none;
                    border: none;
                    font-size: 24px;
                    cursor: pointer;
                    opacity: 0.4;
                    transition: opacity 0.2s;
                  "
                  onmouseover="this.style.opacity='1'"
                  onmouseout="this.style.opacity='0.4'"
          >
            ${star <= 3 ? '⭐' : '✨'}
          </button>
        `).join('')}
      </div>
      <textarea placeholder="Optional: any feedback?"
                id="feedback-text-${toolName}"
                style="
                  width: 100%;
                  padding: 8px;
                  border: 1px solid #ddd;
                  border-radius: 4px;
                  font-family: sans-serif;
                  font-size: 12px;
                  resize: vertical;
                  min-height: 50px;
                "></textarea>
      <button onclick="submitFeedback('${toolName}')" style="
        margin-top: 8px;
        padding: 6px 12px;
        background: #4CAF50;
        color: white;
        border: none;
        border-radius: 4px;
        cursor: pointer;
        font-size: 12px;
      ">Submit Feedback</button>
    </div>
  `;

  document.getElementById('results').appendChild(feedback);
}

function rateTool(toolName, rating) {
  const buttons = document.querySelectorAll(`#feedback-${toolName} .star`);
  buttons.forEach((btn, idx) => {
    btn.style.opacity = idx < rating ? '1' : '0.4';
  });
  document.getElementById(`feedback-${toolName}`).dataset.rating = rating;
}

function submitFeedback(toolName) {
  const rating = parseInt(document.getElementById(`feedback-${toolName}`).dataset.rating || 0);
  const comment = document.getElementById(`feedback-text-${toolName}`).value;

  fetch('/api/feedback', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      tool: toolName,
      rating: rating,
      comment: comment,
      timestamp: new Date().toISOString()
    })
  }).then(r => r.json()).then(data => {
    if (data.ok) {
      document.getElementById(`feedback-${toolName}`).innerHTML =
        "✅ Thank you for the feedback!";
    }
  });
}

// ─── Improvement #4: Weekly Insights Dashboard ───────────────────────────────

function showInsightsDashboard(insightsData) {
  const dashboard = document.createElement('div');
  dashboard.className = 'insights-dashboard';
  dashboard.innerHTML = `
    <div style="
      background: white;
      border-radius: 8px;
      padding: 20px;
      margin: 20px 0;
      border-left: 4px solid #2196F3;
    ">
      <h2>📊 This Week's Insights</h2>

      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin: 20px 0;">
        <div>
          <h3>Most Used Tools</h3>
          <ul style="list-style: none; padding: 0;">
            ${insightsData.most_used.map(([tool, count]) => `
              <li>• <code>${tool}</code>: ${count} times</li>
            `).join('')}
          </ul>
        </div>

        <div>
          <h3>Success Rates</h3>
          <ul style="list-style: none; padding: 0;">
            ${Object.entries(insightsData.success_rates).map(([tool, rate]) => {
              const pct = Math.round(rate * 100);
              const color = pct >= 90 ? '#4CAF50' : pct >= 80 ? '#FF9800' : '#F44336';
              return `
                <li>
                  • <code>${tool}</code>:
                  <span style="color: ${color}; font-weight: bold;">${pct}%</span>
                </li>
              `;
            }).join('')}
          </ul>
        </div>
      </div>

      ${insightsData.suggestions ? `
      <div style="background: #f0f7ff; padding: 12px; border-radius: 4px; margin-top: 16px;">
        <h3>💡 Suggestions</h3>
        <ul style="margin: 8px 0;">
          ${insightsData.suggestions.map(s => `<li>${s}</li>`).join('')}
        </ul>
      </div>
      ` : ''}
    </div>
  `;

  document.getElementById('results').appendChild(dashboard);
}

// ─── Improvement #5: Community Knowledge Search ───────────────────────────────

function showCommunityResults(problem, results) {
  const container = document.createElement('div');
  container.style.cssText = `
    background: #fff3e0;
    border: 1px solid #FFB74D;
    border-radius: 6px;
    padding: 16px;
    margin: 12px 0;
  `;

  container.innerHTML = `
    <h3>🔍 What Others Experienced</h3>
    <p style="color: #666; margin: 0 0 12px 0;">
      Community discussions about "${problem}":
    </p>

    ${results.map((result, i) => `
      <div style="
        margin: 12px 0;
        padding: 12px;
        background: white;
        border-radius: 4px;
        border-left: 4px solid #FF9800;
      ">
        <div style="font-weight: bold;">
          ${i+1}. ${result.source}
          ${result.upvotes ? `(${result.upvotes} upvotes)` : ''}
        </div>
        <div style="color: #333; margin: 8px 0;">
          <strong>${result.title}</strong>
        </div>
        <div style="color: #666; font-size: 12px; margin: 8px 0;">
          ${result.solution.substring(0, 150)}...
        </div>
        <a href="${result.url}" target="_blank" style="
          color: #2196F3;
          text-decoration: none;
          font-size: 12px;
        ">Read full discussion →</a>
      </div>
    `).join('')}
  `;

  document.getElementById('results').appendChild(container);
}

// Helper: Add message to chat
function addMessage(role, content) {
  const msg = document.createElement('div');
  msg.className = `message message-${role.toLowerCase()}`;
  msg.innerHTML = content;
  document.getElementById('results').appendChild(msg);
  document.getElementById('results').scrollTop = document.getElementById('results').scrollHeight;
}
