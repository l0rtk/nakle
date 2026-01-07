# Deployment Guide

## Automated Deployment with GitHub Actions

This repository includes a GitHub Actions workflow that automatically deploys to your Azure VM on every push to the `main` branch.

### Setup Instructions

#### 1. Generate SSH Key on Azure VM

```bash
# On your Azure VM
ssh-keygen -t ed25519 -C "github-actions"
# Press Enter to save to default location (~/.ssh/id_ed25519)
# Press Enter twice for no passphrase

# Add the public key to authorized_keys
cat ~/.ssh/id_ed25519.pub >> ~/.ssh/authorized_keys

# Display the private key (you'll need this for GitHub secrets)
cat ~/.ssh/id_ed25519
```

#### 2. Configure GitHub Secrets

Go to your GitHub repository settings:
1. Navigate to **Settings** → **Secrets and variables** → **Actions**
2. Click **New repository secret** and add the following secrets:

| Secret Name | Value | Example |
|-------------|-------|---------|
| `AZURE_VM_HOST` | Your VM's public IP address | `20.64.142.209` |
| `AZURE_VM_USERNAME` | Your VM username | `azureuser` |
| `AZURE_VM_SSH_KEY` | Private SSH key content | Content of `~/.ssh/id_ed25519` |

**Important**: When copying the SSH private key, include the entire content including:
```
-----BEGIN OPENSSH PRIVATE KEY-----
...
-----END OPENSSH PRIVATE KEY-----
```

#### 3. Initial Setup on Azure VM

Before the first automated deployment, ensure the repository is cloned and configured:

```bash
# On Azure VM
cd ~
git clone https://github.com/l0rtk/nakle.git
cd nakle

# Copy Claude binary
cp ~/.npm-global/bin/claude ./

# Update docker-compose.yml for Azure
sed -i '14s/^/# /' docker-compose.yml
sed -i '16s/^# //' docker-compose.yml

# Verify the change
grep -n "azureuser\|/home/luka" docker-compose.yml
```

#### 4. Test Deployment

After setting up the secrets:

1. Make a small change to your repository
2. Commit and push to `main` branch
3. Go to **Actions** tab in GitHub
4. Watch the deployment workflow run
5. Verify deployment:
   ```bash
   curl -X POST http://<YOUR_VM_IP>/chat/completions \
     -H "Content-Type: application/json" \
     -d '{"model": "haiku", "messages": [{"role": "user", "content": "Hello"}]}'
   ```

### Manual Deployment

You can also trigger deployment manually:

1. Go to **Actions** tab in GitHub
2. Select **Deploy to Azure VM** workflow
3. Click **Run workflow**
4. Select the `main` branch
5. Click **Run workflow**

### Troubleshooting

#### SSH Connection Failed
- Verify `AZURE_VM_HOST` is the correct public IP
- Ensure Azure VM security group allows SSH (port 22) from GitHub Actions IPs
- Check that the SSH key is correctly formatted in the secret

#### Deployment Failed
- Check GitHub Actions logs for specific errors
- SSH into VM manually and check Docker logs:
  ```bash
  sudo docker logs -f nakle-nakle-1
  ```

#### Permission Denied
- Ensure the user has sudo permissions without password:
  ```bash
  echo "$USER ALL=(ALL) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/$USER
  ```

### Workflow File Location

The GitHub Actions workflow is defined in:
```
.github/workflows/deploy.yml
```

### What the Workflow Does

1. Connects to your Azure VM via SSH
2. Navigates to the `nakle` directory
3. Pulls the latest code from GitHub
4. Stops the running Docker container
5. Rebuilds and starts the container with updated code
6. Verifies the container is running

### Security Notes

- Never commit SSH keys to the repository
- Use GitHub Secrets for all sensitive information
- Consider using a dedicated deployment SSH key with limited permissions
- Regularly rotate SSH keys
- Monitor deployment logs for suspicious activity
