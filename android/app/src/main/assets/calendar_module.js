(function() {
    'use strict';

    // Aadress tuleb kasutaja seadistusest (ServerSetupActivity ->
    // SharedPreferences -> AndroidBridge.getBaseUrls()).
    // VAIKEAADRESSI EI OLE: kui server on seadistamata, jääb see tühjaks
    // ja kalendri päringud ei lähe kuhugi – kasutaja suunatakse
    // seadistusekraanile (vt index.html).
const MAYA_BASE_URL = (function () {
    try {
        if (window.MAYA_CFG && window.MAYA_CFG.base) return window.MAYA_CFG.base;
        if (window.AndroidBridge && AndroidBridge.getBaseUrls)
            return JSON.parse(AndroidBridge.getBaseUrls()).base || '';
    } catch (e) { console.warn('MAYA: serveri aadressi lugemine nurjus', e); }
    return '';
})();

    const now = new Date();
    const todayStr = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;

    const state = {
        isOpen: false,
        view: 'month',
        currentDate: new Date(),
        selectedDateStr: todayStr,
        reminders: [],
        editingId: null,
        editNotifyType: 'call'
    };

    const style = document.createElement('style');
    style.textContent = `
        .maya-cal-btn {
            position: fixed;
            top: 18px;
            right: 76px;
            z-index: 1000;
            width: 44px;
            height: 44px;
            border-radius: 14px;
            background: rgba(18, 24, 38, 0.75);
            border: 1px solid rgba(0, 240, 255, 0.35);
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            color: #00f0ff;
            box-shadow: 0 4px 20px rgba(0, 240, 255, 0.2);
            transition: transform 0.2s;
        }
        .maya-cal-btn:active { transform: scale(0.92); }
        #mayaCalModal {
            position: fixed;
            inset: 0;
            z-index: 99999;
            background: rgba(7, 10, 19, 0.94);
            backdrop-filter: blur(25px);
            -webkit-backdrop-filter: blur(25px);
            display: none;
            flex-direction: column;
            color: #e2e8f0;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            user-select: none;
        }
        #mayaCalModal.active { display: flex; }
        .mcal-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 16px 20px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.08);
            background: rgba(15, 23, 42, 0.85);
        }
        .mcal-title {
            font-size: 16px;
            font-weight: 700;
            background: linear-gradient(135deg, #00f0ff, #a855f7);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .mcal-close {
            background: rgba(255, 255, 255, 0.06);
            border: 1px solid rgba(255, 255, 255, 0.12);
            color: #cbd5e1;
            width: 36px;
            height: 36px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            font-size: 18px;
        }
        .mcal-tabs {
            display: flex;
            gap: 8px;
            padding: 10px 20px;
            background: rgba(10, 15, 28, 0.6);
            border-bottom: 1px solid rgba(255, 255, 255, 0.06);
        }
        .mcal-tab {
            flex: 1;
            padding: 8px 0;
            text-align: center;
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 10px;
            color: #94a3b8;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
        }
        .mcal-tab.active {
            background: rgba(0, 240, 255, 0.15);
            border-color: #00f0ff;
            color: #00f0ff;
        }
        .mcal-body {
            flex: 1;
            overflow-y: auto;
            padding: 16px 20px 40px 20px;
        }
        .mcal-nav {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 14px;
        }
        .mcal-nav-title { font-size: 16px; font-weight: 700; color: #f8fafc; }
        .mcal-nav-btn {
            background: rgba(255, 255, 255, 0.06);
            border: 1px solid rgba(255, 255, 255, 0.12);
            color: #cbd5e1;
            padding: 6px 14px;
            border-radius: 8px;
            font-size: 13px;
            cursor: pointer;
        }
        .mcal-grid {
            display: grid;
            grid-template-columns: repeat(7, 1fr);
            gap: 6px;
            text-align: center;
        }
        .mcal-weekday { font-size: 11px; font-weight: 600; color: #64748b; padding-bottom: 4px; }
        .mcal-day {
            aspect-ratio: 1;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            background: rgba(255, 255, 255, 0.02);
            border: 1px solid rgba(255, 255, 255, 0.06);
            border-radius: 10px;
            font-size: 14px;
            color: #cbd5e1;
            cursor: pointer;
            position: relative;
        }
        .mcal-day.today { border-color: rgba(0, 240, 255, 0.5); color: #00f0ff; font-weight: 700; }
        .mcal-day.selected {
            background: rgba(0, 240, 255, 0.22);
            border-color: #00f0ff;
            color: #fff;
            box-shadow: 0 0 12px rgba(0, 240, 255, 0.35);
        }
        .mcal-dot {
            width: 5px;
            height: 5px;
            border-radius: 50%;
            background: #00ff88;
            box-shadow: 0 0 6px #00ff88;
            position: absolute;
            bottom: 4px;
        }
        .mcal-section-box {
            margin-top: 18px;
            background: rgba(18, 24, 38, 0.6);
            border: 1px solid rgba(0, 240, 255, 0.25);
            border-radius: 16px;
            padding: 16px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.3);
        }
        .mcal-badge-pill {
            font-size: 11px;
            padding: 3px 8px;
            border-radius: 6px;
            background: rgba(0, 240, 255, 0.15);
            color: #00f0ff;
            border: 1px solid rgba(0, 240, 255, 0.3);
        }
        .mcal-btn-del {
            background: rgba(255, 50, 100, 0.15);
            border: 1px solid rgba(255, 50, 100, 0.3);
            color: #ff3366;
            border-radius: 8px;
            padding: 5px 10px;
            font-size: 12px;
            cursor: pointer;
            font-weight: 600;
        }
        .mcal-btn-del:active { transform: scale(0.95); }
        .mcal-btn-edit {
            background: rgba(0, 240, 255, 0.15);
            border: 1px solid rgba(0, 240, 255, 0.35);
            color: #00f0ff;
            border-radius: 8px;
            padding: 5px 10px;
            font-size: 12px;
            cursor: pointer;
            font-weight: 600;
            margin-right: 6px;
        }
        .mcal-btn-edit:active { transform: scale(0.95); }
        .mcal-input-row { display: flex; gap: 10px; margin-bottom: 10px; }
        .mcal-input {
            width: 100%;
            background: rgba(10, 15, 28, 0.7);
            border: 1px solid rgba(255, 255, 255, 0.12);
            border-radius: 10px;
            padding: 10px 12px;
            color: #fff;
            font-size: 14px;
            box-sizing: border-box;
            outline: none;
        }
        .mcal-input:focus { border-color: #00f0ff; }
        .mcal-type-toggle { display: flex; gap: 8px; margin-bottom: 12px; }
        .mcal-type-opt {
            flex: 1;
            padding: 10px;
            border-radius: 10px;
            background: rgba(255, 255, 255, 0.04);
            border: 1px solid rgba(255, 255, 255, 0.1);
            text-align: center;
            font-size: 13px;
            font-weight: 600;
            color: #94a3b8;
            cursor: pointer;
            transition: all 0.2s;
        }
        .mcal-type-opt.active {
            background: rgba(0, 240, 255, 0.2);
            border-color: #00f0ff;
            color: #00f0ff;
        }
        .mcal-submit-btn {
            width: 100%;
            padding: 13px;
            background: linear-gradient(135deg, #00f0ff, #7000ff);
            border: none;
            border-radius: 12px;
            color: #fff;
            font-weight: 700;
            font-size: 14px;
            cursor: pointer;
            margin-top: 10px;
        }
        .mcal-submit-btn:active { transform: scale(0.98); }
        
        .mcal-edit-box {
            background: rgba(15, 23, 42, 0.95);
            border: 1px solid #00f0ff;
            border-radius: 12px;
            padding: 12px;
            margin-top: 8px;
            box-shadow: 0 0 15px rgba(0, 240, 255, 0.2);
        }
        .mcal-edit-actions {
            display: flex;
            gap: 8px;
            margin-top: 10px;
        }
        .mcal-btn-save-edit {
            flex: 1;
            background: #00f0ff;
            color: #050b14;
            border: none;
            border-radius: 8px;
            padding: 8px;
            font-size: 13px;
            font-weight: 700;
            cursor: pointer;
        }
        .mcal-btn-cancel-edit {
            flex: 1;
            background: rgba(255, 255, 255, 0.1);
            color: #cbd5e1;
            border: 1px solid rgba(255, 255, 255, 0.15);
            border-radius: 8px;
            padding: 8px;
            font-size: 13px;
            cursor: pointer;
        }
        .mcal-year-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
        .mcal-mini-month {
            background: rgba(18, 24, 38, 0.5);
            border: 1px solid rgba(255, 255, 255, 0.06);
            border-radius: 12px;
            padding: 10px 6px;
            text-align: center;
            cursor: pointer;
        }
        .mcal-mini-title { font-size: 12px; font-weight: 700; color: #00f0ff; margin-bottom: 6px; }
        .mcal-mini-grid { display: grid; grid-template-columns: repeat(7, 1fr); gap: 2px; font-size: 8px; color: #64748b; }
        .mcal-mini-day.has-rem { background: rgba(0, 255, 136, 0.3); border-radius: 2px; color: #00ff88; font-weight: 700; }
    `;
    document.head.appendChild(style);

    const btn = document.createElement('div');
    btn.className = 'maya-cal-btn';
    btn.id = 'mayaCalToggleBtn';
    btn.innerHTML = `
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="3" y="4" width="18" height="18" rx="3" ry="3"></rect>
            <line x1="16" y1="2" x2="16" y2="6"></line>
            <line x1="8" y1="2" x2="8" y2="6"></line>
            <line x1="3" y1="10" x2="21" y2="10"></line>
        </svg>
    `;
    document.body.appendChild(btn);

    const modal = document.createElement('div');
    modal.id = 'mayaCalModal';
    modal.innerHTML = `
        <div class="mcal-header">
            <div class="mcal-title">MAYA AJA- JA KÕNEKALENDER</div>
            <div class="mcal-close" id="mayaCalClose">✕</div>
        </div>
        <div class="mcal-tabs">
            <div class="mcal-tab active" data-view="month">Kuu vaade</div>
            <div class="mcal-tab" data-view="all">Kõik sündmused</div>
            <div class="mcal-tab" data-view="year">Terve aasta</div>
        </div>
        <div class="mcal-body" id="mayaCalContent"></div>
    `;
    document.body.appendChild(modal);

    const monthNames = ["Jaanuar", "Veebruar", "Märts", "Aprill", "Mai", "Juuni", "Juuli", "August", "September", "Oktoober", "November", "Detsember"];
    let selectedNotifyType = 'call';

    async function fetchReminders() {
        try {
            const res = await fetch(`${MAYA_BASE_URL}/api/reminders`);
            if (!res.ok) return;
            const data = await res.json();
            state.reminders = data.reminders || [];
            if (state.isOpen) renderView();
        } catch(e) {}
    }

    async function deleteReminder(id) {
        if (!confirm("Kas soovid selle sündmuse kustutada?")) return;
        try {
            const res = await fetch(`${MAYA_BASE_URL}/api/reminders/${id}`, { method: 'DELETE' });
            if (res.ok) {
                await fetchReminders();
            } else {
                alert("Kustutamisel tekkis tõrge!");
            }
        } catch(e) {
            alert("Võrgu viga: " + e.message);
        }
    }

    async function saveEditedReminder(id, newTitle, newSpeech, newType) {
        try {
            const fd = new FormData();
            fd.append('reminder_text', newTitle);
            fd.append('custom_speech', newSpeech || newTitle);
            fd.append('notify_type', newType);

            const res = await fetch(`${MAYA_BASE_URL}/api/reminders/${id}/update`, {
                method: 'POST',
                body: fd
            });
            if (!res.ok) throw new Error("Viga salvestamisel: " + res.status);
            state.editingId = null;
            await fetchReminders();
        } catch(e) {
            alert("Muudatuse salvestamise viga: " + e.message);
        }
    }

    function renderView() {
        const content = document.getElementById('mayaCalContent');
        if (!content) return;

        if (state.view === 'month') {
            renderMonthView(content);
        } else if (state.view === 'all') {
            renderAllView(content);
        } else if (state.view === 'year') {
            renderYearView(content);
        }
    }

    function renderCard(r) {
        const isVoice = (r.notify_type !== 'notification');
        const typeIcon = isVoice ? '📞 Häälkõne' : '💬 Vaikne tekst';
        const isEditing = (state.editingId === r.id);

        if (isEditing) {
            return `
                <div class="mcal-edit-box">
                    <div style="font-size:12px; font-weight:700; color:#00f0ff; margin-bottom:8px;">MUUDA SÜNDMUST: ${r.trigger_time}</div>
                    
                    <label style="font-size:11px; color:#94a3b8; display:block; margin-bottom:4px;">Teavituse tüüp:</label>
                    <div class="mcal-type-toggle" style="margin-bottom:8px;">
                        <div class="mcal-type-opt ${state.editNotifyType === 'call' ? 'active' : ''}" data-edit-toggle="call">📞 Häälkõne</div>
                        <div class="mcal-type-opt ${state.editNotifyType === 'notification' ? 'active' : ''}" data-edit-toggle="notification">💬 Vaikne tekst</div>
                    </div>

                    <label style="font-size:11px; color:#94a3b8; display:block; margin-bottom:3px;">Teema / Pealkiri:</label>
                    <input type="text" id="mcalEditTitle_${r.id}" class="mcal-input" value="${(r.reminder_text || '').replace(/"/g, '&quot;')}" style="margin-bottom:8px;">

                    <label style="font-size:11px; color:#94a3b8; display:block; margin-bottom:3px;">Kõnetekst / Sõnum:</label>
                    <input type="text" id="mcalEditSpeech_${r.id}" class="mcal-input" value="${(r.custom_speech || '').replace(/"/g, '&quot;')}" style="margin-bottom:8px;">

                    <div class="mcal-edit-actions">
                        <button class="mcal-btn-save-edit" data-save-id="${r.id}">Salvesta muudatus</button>
                        <button class="mcal-btn-cancel-edit" data-cancel-id="${r.id}">Loobu</button>
                    </div>
                </div>
            `;
        }

        return `
            <div style="background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.08); border-radius:12px; padding:10px 12px; margin-bottom:10px;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
                    <span class="mcal-badge-pill">${r.trigger_time.slice(11)} • ${typeIcon} • ${r.repeat_type || 'none'}</span>
                    <div>
                        <button class="mcal-btn-edit" data-edit-id="${r.id}">Muuda</button>
                        <button class="mcal-btn-del" data-del-id="${r.id}">Kustuta</button>
                    </div>
                </div>
                <div style="font-weight:600; color:#fff; font-size:14px;">${r.reminder_text}</div>
                ${r.custom_speech ? `<div style="font-size:12px; color:#94a3b8; margin-top:3px;">"${r.custom_speech}"</div>` : ''}
            </div>
        `;
    }

    function bindCardEvents(el) {
        el.querySelectorAll('.mcal-btn-edit').forEach(b => {
            b.onclick = () => {
                const id = parseInt(b.getAttribute('data-edit-id'));
                const rem = state.reminders.find(r => r.id === id);
                if (rem) {
                    state.editingId = id;
                    state.editNotifyType = rem.notify_type || 'call';
                    renderView();
                }
            };
        });

        el.querySelectorAll('.mcal-btn-del').forEach(b => {
            b.onclick = () => deleteReminder(b.getAttribute('data-del-id'));
        });

        el.querySelectorAll('[data-edit-toggle]').forEach(tog => {
            tog.onclick = () => {
                state.editNotifyType = tog.getAttribute('data-edit-toggle');
                renderView();
            };
        });

        el.querySelectorAll('.mcal-btn-save-edit').forEach(sb => {
            sb.onclick = () => {
                const id = parseInt(sb.getAttribute('data-save-id'));
                const titleVal = document.getElementById(`mcalEditTitle_${id}`).value.trim();
                const speechVal = document.getElementById(`mcalEditSpeech_${id}`).value.trim();
                if (!titleVal) { alert("Pealkiri ei tohi olla tühi!"); return; }
                saveEditedReminder(id, titleVal, speechVal, state.editNotifyType);
            };
        });

        el.querySelectorAll('.mcal-btn-cancel-edit').forEach(cb => {
            cb.onclick = () => {
                state.editingId = null;
                renderView();
            };
        });
    }

    function renderMonthView(el) {
        const year = state.currentDate.getFullYear();
        const month = state.currentDate.getMonth();
        const firstDay = new Date(year, month, 1).getDay();
        const startingDay = (firstDay === 0 ? 6 : firstDay - 1);
        const daysInMonth = new Date(year, month + 1, 0).getDate();

        let html = `
            <div class="mcal-nav">
                <button class="mcal-nav-btn" id="mcalPrevMonth">❮ Eelmine</button>
                <div class="mcal-nav-title">${monthNames[month]} ${year}</div>
                <button class="mcal-nav-btn" id="mcalNextMonth">Järgmine ❯</button>
            </div>
            <div class="mcal-grid">
                <div class="mcal-weekday">E</div><div class="mcal-weekday">T</div><div class="mcal-weekday">K</div>
                <div class="mcal-weekday">N</div><div class="mcal-weekday">R</div><div class="mcal-weekday">L</div><div class="mcal-weekday">P</div>
        `;

        for (let i = 0; i < startingDay; i++) html += `<div></div>`;

        for (let d = 1; d <= daysInMonth; d++) {
            const dStr = `${year}-${String(month + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
            const isToday = (dStr === todayStr);
            const isSel = (dStr === state.selectedDateStr);
            const hasRem = state.reminders.some(r => r.trigger_time && r.trigger_time.startsWith(dStr));

            html += `
                <div class="mcal-day ${isToday ? 'today' : ''} ${isSel ? 'selected' : ''}" data-date="${dStr}">
                    ${d}
                    ${hasRem ? '<span class="mcal-dot"></span>' : ''}
                </div>
            `;
        }
        html += `</div>`;

        const dayRems = state.reminders.filter(r => r.trigger_time && r.trigger_time.startsWith(state.selectedDateStr));

        html += `
            <div class="mcal-section-box">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
                    <span style="font-size:15px; font-weight:700; color:#00f0ff;">Päev: ${state.selectedDateStr}</span>
                    <span style="font-size:12px; color:#94a3b8;">${dayRems.length} sündmust</span>
                </div>
        `;

        if (dayRems.length > 0) {
            dayRems.forEach(r => {
                html += renderCard(r);
            });
        } else {
            html += `<div style="color:#64748b; font-size:13px; margin-bottom:10px;">Sellel päeval pole sündmusi ajastatud.</div>`;
        }

        html += `
                <div style="margin-top:14px; border-top:1px solid rgba(255,255,255,0.08); padding-top:14px;">
                    <div style="font-weight:700; font-size:13px; color:#e2e8f0; margin-bottom:8px;">+ MÄÄRA UUS MEELDETULETUS</div>
                    
                    <label style="font-size:11px; color:#94a3b8; margin-bottom:4px; display:block;">Teavituse tüüp:</label>
                    <div class="mcal-type-toggle">
                        <div class="mcal-type-opt ${selectedNotifyType === 'call' ? 'active' : ''}" data-type="call">📞 Häälkõne</div>
                        <div class="mcal-type-opt ${selectedNotifyType === 'notification' ? 'active' : ''}" data-type="notification">💬 Vaikne teavitus</div>
                    </div>

                    <div class="mcal-input-row">
                        <div style="flex:1;">
                            <label style="font-size:11px; color:#94a3b8;">Kellaaeg:</label>
                            <input type="time" id="mcalInputTime" class="mcal-input" value="09:00">
                        </div>
                        <div style="flex:1.2;">
                            <label style="font-size:11px; color:#94a3b8;">Kordus:</label>
                            <select id="mcalInputRepeat" class="mcal-input">
                                <option value="none">Ühekordne</option>
                                <option value="daily">Iga päev</option>
                                <option value="workdays">Tööpäeviti (E-R)</option>
                                <option value="weekly">Kord nädalas</option>
                            </select>
                        </div>
                    </div>

                    <label style="font-size:11px; color:#94a3b8;">Teema / Pealkiri:</label>
                    <input type="text" id="mcalInputTitle" class="mcal-input" placeholder="nt Vitamiinid, saun, arve" style="margin-bottom:10px;">

                    <label style="font-size:11px; color:#94a3b8;">Sõnumi sisu (mida Maya kõnes ütleb või teatesse saadab):</label>
                    <input type="text" id="mcalInputSpeech" class="mcal-input" placeholder="nt Aeg on minna õue!" style="margin-bottom:6px;">

                    <button class="mcal-submit-btn" id="mcalSaveBtn">Salvesta meeldetuletus</button>
                </div>
            </div>
        `;

        el.innerHTML = html;

        el.querySelector('#mcalPrevMonth').onclick = () => {
            state.currentDate.setMonth(state.currentDate.getMonth() - 1);
            renderView();
        };
        el.querySelector('#mcalNextMonth').onclick = () => {
            state.currentDate.setMonth(state.currentDate.getMonth() + 1);
            renderView();
        };
        el.querySelectorAll('.mcal-day[data-date]').forEach(cell => {
            cell.onclick = () => {
                state.selectedDateStr = cell.getAttribute('data-date');
                renderView();
            };
        });

        el.querySelectorAll('.mcal-type-opt[data-type]').forEach(opt => {
            opt.onclick = () => {
                selectedNotifyType = opt.getAttribute('data-type');
                renderView();
            };
        });

        const titleInput = el.querySelector('#mcalInputTitle');
        const speechInput = el.querySelector('#mcalInputSpeech');

        el.querySelector('#mcalSaveBtn').onclick = async () => {
            const time = el.querySelector('#mcalInputTime').value;
            const repeat = el.querySelector('#mcalInputRepeat').value;
            const title = titleInput.value.trim();
            const speech = speechInput.value.trim();

            const finalTitle = title || speech;
            if (!finalTitle) { alert("Palun sisesta meeldetuletuse teema!"); return; }

            const trigger_time = `${state.selectedDateStr} ${time}`;
            try {
                const fd = new FormData();
                fd.append('trigger_time', trigger_time);
                fd.append('reminder_text', finalTitle);
                fd.append('repeat_type', repeat);
                fd.append('custom_speech', speech || finalTitle);
                fd.append('notify_type', selectedNotifyType);

                const res = await fetch(`${MAYA_BASE_URL}/api/reminders`, {
                    method: 'POST',
                    body: fd
                });
                if (!res.ok) throw new Error("Viga koodiga " + res.status);
                titleInput.value = '';
                speechInput.value = '';
                await fetchReminders();
            } catch(e) {
                alert("Salvestamise tõrge: " + e.message);
            }
        };

        bindCardEvents(el);
    }

    function renderAllView(el) {
        let html = `
            <div style="font-size:16px; font-weight:700; color:#00f0ff; margin-bottom:12px;">
                KÕIK SALVESTATUD MEELDETULETUSED (${state.reminders.length})
            </div>
        `;

        if (state.reminders.length === 0) {
            html += `<div style="color:#64748b; font-size:14px; padding:20px 0;">Ühtegi aktiivset meeldetuletust ei ole lisatud.</div>`;
        } else {
            const sorted = [...state.reminders].sort((a,b) => (a.trigger_time > b.trigger_time ? 1 : -1));
            sorted.forEach(r => {
                html += renderCard(r);
            });
        }

        el.innerHTML = html;
        bindCardEvents(el);
    }

    function renderYearView(el) {
        const year = state.currentDate.getFullYear();
        let html = `
            <div class="mcal-nav">
                <button class="mcal-nav-btn" id="mcalPrevYear">❮ ${year - 1}</button>
                <div class="mcal-nav-title">Aasta ${year}</div>
                <button class="mcal-nav-btn" id="mcalNextYear">${year + 1} ❯</button>
            </div>
            <div class="mcal-year-grid">
        `;
        for (let m = 0; m < 12; m++) {
            const daysInM = new Date(year, m + 1, 0).getDate();
            const firstD = new Date(year, m, 1).getDay();
            const startD = (firstD === 0 ? 6 : firstD - 1);

            html += `
                <div class="mcal-mini-month" data-month="${m}">
                    <div class="mcal-mini-title">${monthNames[m]}</div>
                    <div class="mcal-mini-grid">
            `;
            for (let i = 0; i < startD; i++) html += `<div></div>`;
            for (let d = 1; d <= daysInM; d++) {
                const dStr = `${year}-${String(m + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
                const hasRem = state.reminders.some(r => r.trigger_time && r.trigger_time.startsWith(dStr));
                html += `<div class="mcal-mini-day ${hasRem ? 'has-rem' : ''}">${d}</div>`;
            }
            html += `</div></div>`;
        }
        html += `</div>`;
        el.innerHTML = html;

        el.querySelector('#mcalPrevYear').onclick = () => {
            state.currentDate.setFullYear(year - 1);
            renderView();
        };
        el.querySelector('#mcalNextYear').onclick = () => {
            state.currentDate.setFullYear(year + 1);
            renderView();
        };
        el.querySelectorAll('.mcal-mini-month').forEach(mm => {
            mm.onclick = () => {
                state.currentDate.setMonth(parseInt(mm.getAttribute('data-month')));
                state.view = 'month';
                document.querySelectorAll('.mcal-tab').forEach(t => t.classList.toggle('active', t.getAttribute('data-view') === 'month'));
                renderView();
            };
        });
    }

    btn.onclick = () => {
        state.isOpen = true;
        modal.classList.add('active');
        fetchReminders();
        renderView();
    };

    document.getElementById('mayaCalClose').onclick = () => {
        state.isOpen = false;
        modal.classList.remove('active');
    };

    document.querySelectorAll('.mcal-tab').forEach(tab => {
        tab.onclick = () => {
            document.querySelectorAll('.mcal-tab').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            state.view = tab.getAttribute('data-view');
            renderView();
        };
    });

})();
