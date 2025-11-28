// 启动时记录
console.log('Cookie Sniffer service worker 已启动');

// 服务配置
const SERVICES = {
  douyin: {
    name: 'douyin',
    displayName: '抖音',
    domains: ['douyin.com'],
    cookieDomain: '.douyin.com'
  }
};

/**
 * 根据 URL 匹配服务配置
 * @param {string} url - 当前请求的 URL
 * @returns {{name:string,displayName:string,domains:string[],cookieDomain:string}|null} 匹配到的服务或 null
 */
function getServiceFromUrl(url) {
  for (const [key, service] of Object.entries(SERVICES)) {
    if (service.domains.some(domain => url.includes(domain))) {
      return service;
    }
  }
  return null;
}

/**
 * 判断指定服务是否在 5 分钟内已抓取过
 * @param {string} serviceName - 服务名称
 * @returns {Promise<boolean>} 是否跳过抓取
 */
async function shouldSkipCapture(serviceName) {
  return new Promise((resolve) => {
    chrome.storage.local.get([`lastCapture_${serviceName}`], function(result) {
      const lastTime = result[`lastCapture_${serviceName}`];
      if (!lastTime) {
        resolve(false);
        return;
      }
      
      const now = Date.now();
      const fiveMinutes = 5 * 60 * 1000;
      const shouldSkip = (now - lastTime) < fiveMinutes;
      
      if (shouldSkip) {
        console.log(`${serviceName}: 5分钟内已抓取过，跳过`);
      }
      resolve(shouldSkip);
    });
  });
}

/**
 * 检查 Cookie 内容是否发生变化
 * @param {string} serviceName - 服务名称
 * @param {string} newCookie - 新的 Cookie 字符串
 * @returns {Promise<boolean>} 是否发生变化
 */
async function isCookieChanged(serviceName, newCookie) {
  return new Promise((resolve) => {
    chrome.storage.local.get([`cookieData_${serviceName}`], function(result) {
      const existingData = result[`cookieData_${serviceName}`];
      if (!existingData || existingData.cookie !== newCookie) {
        resolve(true);
      } else {
        console.log(`${serviceName}: Cookie内容无变化，跳过`);
        resolve(false);
      }
    });
  });
}

/**
 * 保存 Cookie 数据并触发 Webhook
 * @param {string} serviceName - 服务名称
 * @param {string} url - 来源 URL
 * @param {string} cookie - Cookie 字符串
 * @param {('headers'|'cookies_api')} [source='headers'] - Cookie 来源
 */
async function saveCookieData(serviceName, url, cookie, source = 'headers') {
  const cookieData = {
    service: serviceName,
    url: url,
    timestamp: Date.now(),
    lastUpdate: new Date().toISOString(),
    cookie: cookie,
    source: source
  };
  
  // 保存服务数据
  chrome.storage.local.set({
    [`cookieData_${serviceName}`]: cookieData,
    [`lastCapture_${serviceName}`]: Date.now()
  });
  
  // 触发Webhook回调
  await sendWebhook(serviceName, cookie);
  
  console.log(`${serviceName}: Cookie已保存`);
}

/**
 * 发送 Webhook 回调通知
 * @param {string} serviceName - 服务名称
 * @param {string} cookie - Cookie 字符串
 */
async function sendWebhook(serviceName, cookie) {
  chrome.storage.local.get(['webhookUrl'], function(result) {
    const webhookUrl = result.webhookUrl;
    if (webhookUrl && webhookUrl.trim()) {
      const payload = {
        service: serviceName,
        cookie: cookie,
        timestamp: new Date().toISOString()
      };
      
      fetch(webhookUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload)
      }).then(response => {
        console.log(`Webhook回调成功: ${serviceName}`, response.status);
      }).catch(error => {
        console.error(`Webhook回调失败: ${serviceName}`, error);
      });
    }
  });
}

chrome.webRequest.onBeforeSendHeaders.addListener(
    async function(details) {
      const service = getServiceFromUrl(details.url);
      if (!service) return;
      
      console.log(`请求拦截: ${service.displayName}`, details.url, details.method);
      
      if (details.method === "POST" || details.method === "GET") {
        // 检查5分钟限制
        if (await shouldSkipCapture(service.name)) {
          return;
        }
        
        let cookieFound = false;
        
        // 尝试从请求头获取Cookie
        if (details.requestHeaders) {
          for (let header of details.requestHeaders) {
            if (header.name.toLowerCase() === "cookie") {
              console.log(`从请求头捕获到Cookie: ${service.displayName}`);
              
              // 检查Cookie是否有变化
              if (await isCookieChanged(service.name, header.value)) {
                await saveCookieData(service.name, details.url, header.value, 'headers');
              }
              
              cookieFound = true;
              break;
            }
          }
        }
        
        // 如果请求头没有Cookie，使用cookies API备用方案
        if (!cookieFound) {
          chrome.cookies.getAll({domain: service.cookieDomain}, async function(cookies) {
            if (cookies && cookies.length > 0) {
              console.log(`通过cookies API获取到: ${service.displayName}`, cookies.length, '个cookie');
              const cookieString = cookies.map(c => `${c.name}=${c.value}`).join('; ');
              
              // 检查Cookie是否有变化
              if (await isCookieChanged(service.name, cookieString)) {
                await saveCookieData(service.name, details.url, cookieString, 'cookies_api');
              }
            }
          });
        }
      }
    },
    { urls: ["https://*.douyin.com/*", "https://douyin.com/*"] },
    ["requestHeaders", "extraHeaders"]
  );

// 添加存储变化监听
chrome.storage.onChanged.addListener((changes, areaName) => {
  if (areaName === 'local') {
    // 监听服务数据变化
    Object.keys(changes).forEach(key => {
      if (key.startsWith('cookieData_')) {
        const serviceName = key.replace('cookieData_', '');
        const serviceConfig = SERVICES[serviceName];
        if (serviceConfig && changes[key].newValue) {
          console.log(`${serviceConfig.displayName} Cookie数据已更新`);
        }
      }
    });
  }
});
  
