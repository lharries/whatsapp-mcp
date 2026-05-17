package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"time"
)

type DjangoAPIClient struct {
	baseURL     string
	serviceKey  string
	httpClient  *http.Client
}

func NewDjangoAPIClient(baseURL, serviceKey string) *DjangoAPIClient {
	return &DjangoAPIClient{
		baseURL:    baseURL,
		serviceKey: serviceKey,
		httpClient: &http.Client{
			Timeout: 30 * time.Second,
		},
	}
}

func (c *DjangoAPIClient) newRequest(method, path string, body interface{}) (*http.Request, error) {
	var reqBody *bytes.Buffer
	if body != nil {
		jsonData, err := json.Marshal(body)
		if err != nil {
			return nil, fmt.Errorf("failed to marshal request body: %w", err)
		}
		reqBody = bytes.NewBuffer(jsonData)
	} else {
		reqBody = &bytes.Buffer{}
	}

	url := c.baseURL + path
	req, err := http.NewRequest(method, url, reqBody)
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %w", err)
	}

	req.Header.Set("X-Service-Key", c.serviceKey)
	req.Header.Set("Content-Type", "application/json")

	return req, nil
}

func (c *DjangoAPIClient) doRequest(ctx context.Context, req *http.Request) (*http.Response, error) {
	req = req.WithContext(ctx)
	return c.httpClient.Do(req)
}

func (c *DjangoAPIClient) GetUsers(ctx context.Context) ([]UserInfo, error) {
	req, err := c.newRequest(http.MethodGet, "/api/users/", nil)
	if err != nil {
		return nil, err
	}

	resp, err := c.doRequest(ctx, req)
	if err != nil {
		return nil, fmt.Errorf("failed to get users: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("unexpected status code: %d", resp.StatusCode)
	}

	var result struct {
		Results []UserInfo `json:"results"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, fmt.Errorf("failed to decode response: %w", err)
	}

	return result.Results, nil
}

func (c *DjangoAPIClient) GetUser(ctx context.Context, userID int) (*UserInfo, error) {
	req, err := c.newRequest(http.MethodGet, fmt.Sprintf("/api/users/%d/", userID), nil)
	if err != nil {
		return nil, err
	}

	resp, err := c.doRequest(ctx, req)
	if err != nil {
		return nil, fmt.Errorf("failed to get user: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode == http.StatusNotFound {
		return nil, fmt.Errorf("user not found: %d", userID)
	}
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("unexpected status code: %d", resp.StatusCode)
	}

	var user UserInfo
	if err := json.NewDecoder(resp.Body).Decode(&user); err != nil {
		return nil, fmt.Errorf("failed to decode response: %w", err)
	}

	return &user, nil
}

type UpdateUserRequest struct {
	Status      string `json:"status,omitempty"`
	WhatsAppJID string `json:"whatsapp_jid,omitempty"`
}

func (c *DjangoAPIClient) UpdateUser(ctx context.Context, userID int, update UpdateUserRequest) error {
	req, err := c.newRequest(http.MethodPatch, fmt.Sprintf("/api/users/%d/", userID), update)
	if err != nil {
		return err
	}

	resp, err := c.doRequest(ctx, req)
	if err != nil {
		return fmt.Errorf("failed to update user: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("unexpected status code: %d", resp.StatusCode)
	}

	return nil
}

type PushQRRequest struct {
	ImageData string `json:"image_data"`
	ExpiresAt string `json:"expires_at,omitempty"`
}

func (c *DjangoAPIClient) PushQR(ctx context.Context, userID int, imageData string, expiresAt time.Time) error {
	reqBody := PushQRRequest{
		ImageData: imageData,
		ExpiresAt: expiresAt.Format(time.RFC3339),
	}

	req, err := c.newRequest(http.MethodPatch, fmt.Sprintf("/api/users/%d/qr/", userID), reqBody)
	if err != nil {
		return err
	}

	resp, err := c.doRequest(ctx, req)
	if err != nil {
		return fmt.Errorf("failed to push QR: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("unexpected status code: %d", resp.StatusCode)
	}

	return nil
}

func (c *DjangoAPIClient) UpdateUserStatus(ctx context.Context, userID int, status string) error {
	return c.UpdateUser(ctx, userID, UpdateUserRequest{Status: status})
}