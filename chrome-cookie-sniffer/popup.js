document.addEventListener('DOMContentLoaded', function() {
    const refreshBtn = document.getElementById('refresh');
    const clearBtn = document.getElementById('clear');
    const exportBtn = document.getElementById('export');
    const webhookInput = document.getElementById('webhookUrl');
    const testWebhookBtn = document.getElementById('testWebhook');
    const webhookStatus = document.getElementById('webhookStatus');
    const statusInfo = document.getElementById('statusInfo');
    const serviceCards = document.getElementById('serviceCards');
    const emptyState = document.getElementById('emptyState');
    
    // 服务配置
    const SERVICES = {
        douyin: { name: 'douyin', displayName: '抖音', icon: '🎵' }
    };
    
    /**
     * 加载存储中的 Webhook 配置
     * @returns {void}
     */
    function loadWebhookConfig() {
        chrome.storage.local.get(['webhookUrl'], function(result) {
            if (result.webhookUrl) {
                webhookInput.value = result.webhookUrl;
            }
            updateTestButtonState();
        });
    }
    
    /**
     * 保存 Webhook 配置到本地存储
     * @returns {void}
     */
    function saveWebhookConfig() {
        const url = webhookInput.value.trim();
        chrome.storage.local.set({ webhookUrl: url });
        showStatusInfo('Webhook地址已保存');
        updateTestButtonState();
    }
    
    /**
     * 根据 Webhook 地址更新测试按钮可用性
     * @returns {void}
     */
    function updateTestButtonState() {
        const url = webhookInput.value.trim();
        testWebhookBtn.disabled = !url || !isValidUrl(url);
    }
    
    /**
     * 验证字符串是否为合法 URL
     * @param {string} string - 待验证的字符串
     * @returns {boolean} 是否合法
     */
    function isValidUrl(string) {
        try {
            new URL(string);
            return string.startsWith('http://') || string.startsWith('https://');
        } catch (_) {
            return false;
        }
    }
    
    /**
     * 发送 Webhook 测试请求
     * @returns {Promise<void>}
     */
    async function testWebhook() {
        const url = webhookInput.value.trim();
        if (!url) {
            webhookStatus.textContent = '请先输入Webhook地址';
            webhookStatus.style.color = '#dc3545';
            return;
        }
        
        testWebhookBtn.disabled = true;
        testWebhookBtn.textContent = '⏳ 测试中...';
        webhookStatus.textContent = '正在发送测试请求...';
        webhookStatus.style.color = '#17a2b8';
        
        // 获取现有数据或创建测试数据
        chrome.storage.local.get(['cookieData_douyin'], async function(result) {
            let testData;
            
            if (result.cookieData_douyin) {
                // 使用现有数据
                testData = {
                    service: 'douyin',
                    cookie: result.cookieData_douyin.cookie,
                    timestamp: new Date().toISOString(),
                    test: true,
                    message: '这是一个测试回调，使用了真实的Cookie数据'
                };
            } else {
                // 使用模拟数据
                testData = {
                    service: 'douyin',
                    cookie: 'test_cookie=test_value; another_cookie=another_value',
                    timestamp: new Date().toISOString(),
                    test: true,
                    message: '这是一个测试回调，使用了模拟Cookie数据'
                };
            }
            
            try {
                const response = await fetch(url, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(testData)
                });
                
                if (response.ok) {
                    webhookStatus.textContent = `✅ 测试成功 (${response.status})`;
                    webhookStatus.style.color = '#28a745';
                } else {
                    webhookStatus.textContent = `❌ 服务器错误 (${response.status})`;
                    webhookStatus.style.color = '#dc3545';
                }
            } catch (error) {
                console.error('Webhook测试失败:', error);
                if (error.name === 'TypeError' && error.message.includes('fetch')) {
                    webhookStatus.textContent = '❌ 网络错误或跨域限制';
                } else {
                    webhookStatus.textContent = `❌ 请求失败: ${error.message}`;
                }
                webhookStatus.style.color = '#dc3545';
            } finally {
                testWebhookBtn.disabled = false;
                testWebhookBtn.textContent = '🔧 测试';
                updateTestButtonState();
                
                // 5秒后清除状态信息
                setTimeout(() => {
                    webhookStatus.textContent = '';
                }, 5000);
            }
        });
    }
    
    /**
     * 在界面展示短暂的状态信息
     * @param {string} message - 状态文本
     * @returns {void}
     */
    function showStatusInfo(message) {
        statusInfo.textContent = message;
        statusInfo.style.display = 'block';
        setTimeout(() => {
            statusInfo.style.display = 'none';
        }, 3000);
    }
    
    /**
     * 加载本地存储中的服务 Cookie 数据
     * @returns {void}
     */
    function loadServiceData() {
        const serviceKeys = Object.keys(SERVICES).map(service => `cookieData_${service}`);
        chrome.storage.local.get(serviceKeys, function(result) {
            const hasData = Object.keys(result).length > 0;
            
            if (!hasData) {
                serviceCards.innerHTML = '';
                emptyState.style.display = 'block';
                return;
            }
            
            emptyState.style.display = 'none';
            serviceCards.innerHTML = '';
            
            Object.keys(SERVICES).forEach(serviceKey => {
                const service = SERVICES[serviceKey];
                const data = result[`cookieData_${serviceKey}`];
                
                if (data) {
                    createServiceCard(service, data);
                }
            });
        });
    }
    
    /**
     * 创建服务数据展示卡片
     * @param {{name:string,displayName:string,icon:string}} service - 服务配置
     * @param {{lastUpdate:string,timestamp:number,cookie:string}} data - 数据对象
     * @returns {void}
     */
    function createServiceCard(service, data) {
        const card = document.createElement('div');
        card.className = 'service-card';
        
        const isRecent = Date.now() - data.timestamp < 5 * 60 * 1000; // 5分钟内
        const lastUpdate = new Date(data.lastUpdate).toLocaleString();
        
        card.innerHTML = `
            <div class="card-header">
                <div class="service-name">${service.icon} ${service.displayName}</div>
                <div class="service-status ${isRecent ? 'status-active' : 'status-inactive'}">
                    ${isRecent ? '活跃' : '休眠'}
                </div>
            </div>
            <div class="card-body">
                <div class="last-update">上次更新: ${lastUpdate}</div>
                <div class="actions">
                    <button class="btn btn-primary btn-sm copy-btn" data-service="${service.name}">
                        📋 复制Cookie
                    </button>
                    <button class="btn btn-danger btn-sm delete-btn" data-service="${service.name}">
                        🗑️ 删除
                    </button>
                </div>
            </div>
        `;
        
        serviceCards.appendChild(card);
    }
    
    /**
     * 复制指定服务的 Cookie 到剪贴板
     * @param {string} serviceName - 服务名称
     * @returns {Promise<void>}
     */
    async function copyCookie(serviceName) {
        chrome.storage.local.get([`cookieData_${serviceName}`], async function(result) {
            const data = result[`cookieData_${serviceName}`];
            if (data && data.cookie) {
                try {
                    await navigator.clipboard.writeText(data.cookie);
                    showStatusInfo(`${SERVICES[serviceName].displayName} Cookie已复制到剪贴板`);
                } catch (err) {
                    // 备用方案
                    const textarea = document.createElement('textarea');
                    textarea.value = data.cookie;
                    document.body.appendChild(textarea);
                    textarea.select();
                    document.execCommand('copy');
                    document.body.removeChild(textarea);
                    showStatusInfo(`${SERVICES[serviceName].displayName} Cookie已复制到剪贴板`);
                }
            }
        });
    }
    
    /**
     * 删除指定服务的存储数据
     * @param {string} serviceName - 服务名称
     * @returns {void}
     */
    function deleteService(serviceName) {
        if (confirm(`确定要删除 ${SERVICES[serviceName].displayName} 的Cookie数据吗？`)) {
            chrome.storage.local.remove([
                `cookieData_${serviceName}`,
                `lastCapture_${serviceName}`
            ], function() {
                loadServiceData();
                showStatusInfo(`${SERVICES[serviceName].displayName} 数据已删除`);
            });
        }
    }
    
    /**
     * 清空所有服务的 Cookie 数据
     * @returns {void}
     */
    function clearAllData() {
        if (confirm('确定要清空所有Cookie数据吗？')) {
            const keysToRemove = [];
            Object.keys(SERVICES).forEach(service => {
                keysToRemove.push(`cookieData_${service}`);
                keysToRemove.push(`lastCapture_${service}`);
            });
            
            chrome.storage.local.remove(keysToRemove, function() {
                loadServiceData();
                showStatusInfo('所有数据已清空');
            });
        }
    }
    
    /**
     * 导出所有服务的 Cookie 数据为 JSON 文件
     * @returns {void}
     */
    function exportData() {
        const serviceKeys = Object.keys(SERVICES).map(service => `cookieData_${service}`);
        chrome.storage.local.get(serviceKeys, function(result) {
            const exportData = {};
            
            Object.keys(result).forEach(key => {
                const serviceName = key.replace('cookieData_', '');
                exportData[serviceName] = result[key];
            });
            
            const blob = new Blob([JSON.stringify(exportData, null, 2)], {type: 'application/json'});
            const url = URL.createObjectURL(blob);
            
            const a = document.createElement('a');
            a.href = url;
            a.download = `cookie-sniffer-${new Date().toISOString().slice(0,10)}.json`;
            a.click();
            
            URL.revokeObjectURL(url);
            showStatusInfo('数据已导出');
        });
    }
    
    // 事件绑定
    refreshBtn.addEventListener('click', loadServiceData);
    clearBtn.addEventListener('click', clearAllData);
    exportBtn.addEventListener('click', exportData);
    webhookInput.addEventListener('blur', saveWebhookConfig);
    webhookInput.addEventListener('input', updateTestButtonState);
    testWebhookBtn.addEventListener('click', testWebhook);
    
    // 代理点击事件
    serviceCards.addEventListener('click', function(e) {
        if (e.target.classList.contains('copy-btn')) {
            const serviceName = e.target.getAttribute('data-service');
            copyCookie(serviceName);
        } else if (e.target.classList.contains('delete-btn')) {
            const serviceName = e.target.getAttribute('data-service');
            deleteService(serviceName);
        }
    });
    
    // 初始化
    loadWebhookConfig();
    loadServiceData();
    
    // 自动刷新（每30秒）
    setInterval(loadServiceData, 30000);
});
