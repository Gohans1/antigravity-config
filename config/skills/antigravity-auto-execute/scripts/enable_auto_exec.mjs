import fs from 'fs';
import path from 'path';
import os from 'os';

const homeDir = os.homedir();
const configDir = path.join(homeDir, '.gemini', 'config');
const globalConfigFile = path.join(configDir, 'config.json');
const projectsDir = path.join(configDir, 'projects');

console.log('=== KÍCH HOẠT ANTIGRAVITY AUTO-EXECUTION (FULL AUTO / EAGER) ===\n');

// 1. Cập nhật Global config.json
if (fs.existsSync(globalConfigFile)) {
  try {
    const raw = fs.readFileSync(globalConfigFile, 'utf8');
    const config = JSON.parse(raw);
    
    // Backup
    const backupFile = globalConfigFile + '.bak';
    fs.writeFileSync(backupFile, raw, 'utf8');
    
    config.userSettings = config.userSettings || {};
    const previous = config.userSettings.autoExecutionPolicy;
    config.userSettings.autoExecutionPolicy = 'CASCADE_COMMANDS_AUTO_EXECUTION_EAGER';
    
    fs.writeFileSync(globalConfigFile, JSON.stringify(config, null, 2), 'utf8');
    console.log(`[OK] Global config đã cập nhật:`);
    console.log(`     - File: ${globalConfigFile}`);
    console.log(`     - Trạng thái cũ: ${previous || 'N/A'}`);
    console.log(`     - Trạng thái mới: CASCADE_COMMANDS_AUTO_EXECUTION_EAGER`);
    console.log(`     - Bản sao lưu: ${backupFile}\n`);
  } catch (err) {
    console.error(`[ERROR] Không thể cập nhật global config: ${err.message}`);
  }
} else {
  console.warn(`[WARN] Không tìm thấy file global config: ${globalConfigFile}`);
}

// 2. Cập nhật tất cả các Project Configs
if (fs.existsSync(projectsDir)) {
  const files = fs.readdirSync(projectsDir).filter(f => f.endsWith('.json'));
  console.log(`Tìm thấy ${files.length} dự án trong thư mục projects/. Đang kích hoạt Eager Mode...`);
  
  let updatedCount = 0;
  for (const file of files) {
    const filePath = path.join(projectsDir, file);
    try {
      const raw = fs.readFileSync(filePath, 'utf8');
      const proj = JSON.parse(raw);
      
      proj.settings = proj.settings || {};
      proj.settings.autoExecutionPolicy = 'CASCADE_COMMANDS_AUTO_EXECUTION_EAGER';
      proj.autoExecutionPolicy = 'CASCADE_COMMANDS_AUTO_EXECUTION_EAGER';
      
      fs.writeFileSync(filePath, JSON.stringify(proj, null, 2), 'utf8');
      console.log(`  + Đã bật cho project: "${proj.name || file}"`);
      updatedCount++;
    } catch (e) {
      console.warn(`  - Bỏ qua file ${file}: ${e.message}`);
    }
  }
  console.log(`\n[OK] Đã cập nhật thành công ${updatedCount}/${files.length} dự án.\n`);
}

console.log('------------------------------------------------------------');
console.log('HOÀN TẤT! Hãy tắt và khởi động lại Antigravity để nhận cấu hình mới.');
console.log('Từ nay Agent sẽ tự động chạy tất cả câu lệnh (Node, Python, Bash,...) mà không dừng lại hỏi Submit.');
