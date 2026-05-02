#!/bin/bash
# 推送到 GitHub 脚本
# 把 <YOUR_GITHUB_TOKEN> 替换成你的 Personal Access Token

TOKEN="<YOUR_GITHUB_TOKEN>"
USERNAME="firecome7"
REPO="crypto-bot"

# 1. 通过 API 创建仓库
curl -s -u "$USERNAME:$TOKEN" \
  -X POST https://api.github.com/user/repos \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"$REPO\",\"private\":false,\"description\":\"Binance USDT perpetual futures auto-trading bot\"}"

# 2. 推代码
cd ~/crypto-bot
git remote set-url origin "https://$USERNAME:$TOKEN@github.com/$USERNAME/$REPO.git"
git push -u origin master
