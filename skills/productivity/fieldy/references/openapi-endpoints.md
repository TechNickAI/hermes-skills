# Fieldy Public API — endpoint inventory

Extracted from https://api.fieldy.ai/docs (OpenAPI 3.1.1, spec version v2.0.0).
Regenerate by parsing the `const scalarConfig = {...}` blob in that page's HTML:
its `content` key holds the whole spec as a JSON string.

Base: `https://api.fieldy.ai/api/public/v2`

## DELETE /conversations/{id}

operationId: `conversations.delete`

| param | in | required | schema |
|---|---|---|---|
| id | path | yes | string |

Request body:

```json
{
 "type": "object",
 "properties": {},
 "required": []
}
```

200 response schema:

```json
{
 "type": "object",
 "properties": {
  "success": {
   "type": "boolean"
  }
 },
 "required": [
  "success"
 ]
}
```

## GET /conversations/{id}

operationId: `conversations.get`

| param | in | required | schema |
|---|---|---|---|
| id | path | yes | string |

200 response schema:

```json
{
 "anyOf": [
  {
   "type": "object",
   "properties": {
    "id": {
     "type": "string"
    },
    "title": {
     "anyOf": [
      {
       "type": "string"
      },
      {
       "type": "null"
      }
     ]
    },
    "summary": {
     "anyOf": [
      {
       "type": "string"
      },
      {
       "type": "null"
      }
     ]
    },
    "content": {
     "anyOf": [
      {
       "type": "string"
      },
      {
       "type": "null"
      }
     ]
    },
    "startTime": {
     "type": "string"
    },
    "endTime": {
     "anyOf": [
      {
       "type": "string"
      },
      {
       "type": "null"
      }
     ]
    },
    "type": {
     "enum": [
      "FULL",
      "BRIEF"
     ],
     "type": "string"
    },
    "keywords": {
     "type": "array",
     "items": {
      "type": "string"
     }
    },
    "speakers": {
     "type": "array",
     "items": {
      "type": "string"
     }
    },
    "memorySpeakers": {
     "type": "array",
     "items": {
      "type": "string"
     },
     "description": "DEPRECATED: use `speakers`. Kept for older client builds."
    },
    "quotes": {
     "type": "array",
     "items": {
      "type": "object",
      "properties": {
       "text": {
        "type": "string"
       },
       "context": {
        "anyOf": [
         {
          "type": "string"
         },
         {
          "type": "null"
         }
        ]
       }
      },
      "required": [
       "text",
       "context"
      ]
     }
    },
    "location": {
     "anyOf": [
      {
       "type": "object",
       "properties": {
        "address": {
         "anyOf": [
          {
           "type": "string"
          },
          {
           "type": "null"
          }
         ]
        },
        "coordinates": {
         "type": "object",
         "properties": {
          "latitude": {
           "type": "number"
          },
          "longitude": {
           "type": "number"
          }
         },
         "required": [
          "latitude",
          "longitude"
         ]
        },
        "country": {
         "anyOf": [
          {
           "type": "string"
          },
          {
           "type": "null"
          }
         ]
        },
        "placeId": {
         "anyOf": [
          {
           "type": "string"
          },
          {
           "type": "null"
          }
         ]
        },
        "zip": {
         "anyOf": [
          {
           "type": "string"
          },
          {
           "type": "null"
          }
         ]
        },
        "street": {
         "anyOf": [
          {
           "type": "string"
          },
          {
           "type": "null"
          }
         ]
        },
        "streetNumber": {
         "anyOf": [
          {
           "type": "string"
          },
          {
           "type": "null"
          }
         ]
        },
        "city": {
         "anyOf": [
          {
           "type": "string"
          },
          {
           "type": "null"
          }
         ]
        }
       },
       "required": [
        "coordinates"
       ]
      },
      {
       "type": "null"
      }
     ]
    },
    "locationId": {
     "anyOf": [
      {
       "type": "string"
      },
      {
       "type": "null"
      }
     ]
    },
    "templateId": {
     "anyOf": [
      {
       "type": "string"
      },
      {
       "type": "null"
      }
     ]
    },
    "memoryTemplateId": {
     "anyOf": [
      {
       "type": "string"
      },
      {
       "type": "null"
      }
     ],
     "description": "DEPRECATED: use `templateId`. Kept for older client builds."
    },
    "recommendedTemplateIds": {
     "anyOf": [
      {
       "type": "array",
       "items": {
        "type": "string"
       }
      },
      {
       "type": "null"
      }
     ]
    },
    "calendarEventId": {
     "anyOf": [
      {
       "type": "string"
      },
      {
       "type": "null"
      }
     ]
    },
    "updatedAt": {
     "type": "string"
    }
   },
   "required": [
    "id",
    "title",
    "summary",
    "content",
    "startTime",
    "endTime",
    "type",
    "keywords",
    "speakers",
    "memorySpeakers",
    "quotes",
    "location",
    "locationId",
    "templateId",
    "memoryTemplateId",
    "recommendedTemplateIds",
    "calendarEventId",
    "updatedAt"
   ]
  },
  {
   "type": "null"
  }
 ]
}
```

## PATCH /conversations/{id}

operationId: `conversations.update`

| param | in | required | schema |
|---|---|---|---|
| id | path | yes | string |

Request body:

```json
{
 "type": "object",
 "properties": {
  "title": {
   "type": "string",
   "description": "Conversation title"
  },
  "summary": {
   "type": "string",
   "description": "AI-generated summary"
  },
  "content": {
   "type": "string",
   "description": "Full transcript content"
  },
  "templateId": {
   "type": "string",
   "description": "Memory template ID"
  },
  "endTime": {
   "type": "string",
   "description": "ISO 8601 end time"
  },
  "location": {
   "type": "object",
   "properties": {
    "address": {
     "anyOf": [
      {
       "type": "string"
      },
      {
       "type": "null"
      }
     ]
    },
    "coordinates": {
     "type": "object",
     "properties": {
      "latitude": {
       "type": "number"
      },
      "longitude": {
       "type": "number"
      }
     },
     "required": [
      "latitude",
      "longitude"
     ]
    },
    "country": {
     "anyOf": [
      {
       "type": "string"
      },
      {
       "type": "null"
      }
     ]
    },
    "placeId": {
     "anyOf": [
      {
       "type": "string"
      },
      {
       "type": "null"
      }
     ]
    },
    "zip": {
     "anyOf": [
      {
       "type": "string"
      },
      {
       "type": "null"
      }
     ]
    },
    "street": {
     "anyOf": [
      {
       "type": "string"
      },
      {
       "type": "null"
      }
     ]
    },
    "streetNumber": {
     "anyOf": [
      {
       "type": "string"
      },
      {
       "type": "null"
      }
     ]
    },
    "city": {
     "anyOf": [
      {
       "type": "string"
      },
      {
       "type": "null"
      }
     ]
    }
   },
   "required": [
    "coordinates"
   ],
   "description": "Location where conversation took place"
  },
  "type": {
   "enum": [
    "FULL",
    "BRIEF"
   ],
   "type": "string",
   "description": "Conversation type"
  },
  "calendarEventId": {
   "type": "string",
   "description": "Associated calendar event ID"
  }
 },
 "required": []
}
```

200 response schema:

```json
{
 "type": "object",
 "properties": {
  "success": {
   "type": "boolean"
  },
  "conversation": {
   "anyOf": [
    {
     "type": "object",
     "properties": {
      "id": {
       "type": "string"
      },
      "title": {
       "anyOf": [
        {
         "type": "string"
        },
        {
         "type": "null"
        }
       ]
      },
      "summary": {
       "anyOf": [
        {
         "type": "string"
        },
        {
         "type": "null"
        }
       ]
      },
      "content": {
       "anyOf": [
        {
         "type": "string"
        },
        {
         "type": "null"
        }
       ]
      },
      "startTime": {
       "type": "string"
      },
      "endTime": {
       "anyOf": [
        {
         "type": "string"
        },
        {
         "type": "null"
        }
       ]
      },
      "type": {
       "enum": [
        "FULL",
        "BRIEF"
       ],
       "type": "string"
      },
      "keywords": {
       "type": "array",
       "items": {
        "type": "string"
       }
      },
      "speakers": {
       "type": "array",
       "items": {
        "type": "string"
       }
      },
      "memorySpeakers": {
       "type": "array",
       "items": {
        "type": "string"
       },
       "description": "DEPRECATED: use `speakers`. Kept for older client builds."
      },
      "quotes": {
       "type": "array",
       "items": {
        "type": "object",
        "properties": {
         "text": {
          "type": "string"
         },
         "context": {
          "anyOf": [
           {
            "type": "string"
           },
           {
            "type": "null"
           }
          ]
         }
        },
        "required": [
         "text",
         "context"
        ]
       }
      },
      "location": {
       "anyOf": [
        {
         "type": "object",
         "properties": {
          "address": {
           "anyOf": [
            {
             "type": "string"
            },
            {
             "type": "null"
            }
           ]
          },
          "coordinates": {
           "type": "object",
           "properties": {
            "latitude": {
             "type": "number"
            },
            "longitude": {
             "type": "number"
            }
           },
           "required": [
            "latitude",
            "longitude"
           ]
          },
          "country": {
           "anyOf": [
            {
             "type": "string"
            },
            {
             "type": "null"
            }
           ]
          },
          "placeId": {
           "anyOf": [
            {
             "type": "string"
            },
            {
             "type": "null"
            }
           ]
          },
          "zip": {
           "anyOf": [
            {
             "type": "string"
            },
            {
             "type": "null"
            }
           ]
          },
          "street": {
           "anyOf": [
            {
             "type": "string"
            },
            {
             "type": "null"
            }
           ]
          },
          "streetNumber": {
           "anyOf": [
            {
             "type": "string"
            },
            {
             "type": "null"
            }
           ]
          },
          "city": {
           "anyOf": [
            {
             "type": "string"
            },
            {
             "type": "null"
            }
           ]
          }
         },
         "required": [
          "coordinates"
         ]
        },
        {
         "type": "null"
        }
       ]
      },
      "locationId": {
       "anyOf": [
        {
         "type": "string"
        },
        {
         "type": "null"
        }
       ]
      },
      "templateId": {
       "anyOf": [
        {
         "type": "string"
        },
        {
         "type": "null"
        }
       ]
      },
      "memoryTemplateId": {
       "anyOf": [
        {
         "type": "string"
        },
        {
         "type": "null"
        }
       ],
       "description": "DEPRECATED: use `templateId`. Kept for older client builds."
      },
      "recommendedTemplateIds": {
       "anyOf": [
        {
         "type": "array",
         "items": {
          "type": "string"
         }
        },
        {
         "type": "null"
        }
       ]
      },
      "calendarEventId": {
       "anyOf": [
        {
         "type": "string"
        },
        {
         "type": "null"
        }
       ]
      },
      "updatedAt": {
       "type": "string"
      }
     },
     "required": [
      "id",
      "title",
      "summary",
      "content",
      "startTime",
      "endTime",
      "type",
      "keywords",
      "speakers",
      "memorySpeakers",
      "quotes",
      "location",
      "locationId",
      "templateId",
      "memoryTemplateId",
      "recommendedTemplateIds",
      "calendarEventId",
      "updatedAt"
     ]
    },
    {
     "type": "null"
    }
   ]
  }
 },
 "required": [
  "success",
  "conversation"
 ]
}
```

## GET /conversations

operationId: `conversations.list`

| param | in | required | schema |
|---|---|---|---|
| startTime | query | yes | string |
| endTime | query | yes | string |
| mode | query | no | enum: starts-in-range/intersects-range, string, default=starts-in-range |
| cursor | query | no | string |
| pageSize | query | no | number, default=6, max=50, min=1 |
| recordingSource | query | no | enum: wearable/phone/desktop, string |

200 response schema:

```json
{
 "type": "object",
 "properties": {
  "items": {
   "type": "array",
   "items": {
    "type": "object",
    "properties": {
     "id": {
      "type": "string"
     },
     "title": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ]
     },
     "summary": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ]
     },
     "content": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ]
     },
     "startTime": {
      "type": "string"
     },
     "endTime": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ]
     },
     "type": {
      "enum": [
       "FULL",
       "BRIEF"
      ],
      "type": "string"
     },
     "keywords": {
      "type": "array",
      "items": {
       "type": "string"
      }
     },
     "speakers": {
      "type": "array",
      "items": {
       "type": "string"
      }
     },
     "memorySpeakers": {
      "type": "array",
      "items": {
       "type": "string"
      },
      "description": "DEPRECATED: use `speakers`. Kept for older client builds."
     },
     "quotes": {
      "type": "array",
      "items": {
       "type": "object",
       "properties": {
        "text": {
         "type": "string"
        },
        "context": {
         "anyOf": [
          {
           "type": "string"
          },
          {
           "type": "null"
          }
         ]
        }
       },
       "required": [
        "text",
        "context"
       ]
      }
     },
     "location": {
      "anyOf": [
       {
        "type": "object",
        "properties": {
         "address": {
          "anyOf": [
           {
            "type": "string"
           },
           {
            "type": "null"
           }
          ]
         },
         "coordinates": {
          "type": "object",
          "properties": {
           "latitude": {
            "type": "number"
           },
           "longitude": {
            "type": "number"
           }
          },
          "required": [
           "latitude",
           "longitude"
          ]
         },
         "country": {
          "anyOf": [
           {
            "type": "string"
           },
           {
            "type": "null"
           }
          ]
         },
         "placeId": {
          "anyOf": [
           {
            "type": "string"
           },
           {
            "type": "null"
           }
          ]
         },
         "zip": {
          "anyOf": [
           {
            "type": "string"
           },
           {
            "type": "null"
           }
          ]
         },
         "street": {
          "anyOf": [
           {
            "type": "string"
           },
           {
            "type": "null"
           }
          ]
         },
         "streetNumber": {
          "anyOf": [
           {
            "type": "string"
           },
           {
            "type": "null"
           }
          ]
         },
         "city": {
          "anyOf": [
           {
            "type": "string"
           },
           {
            "type": "null"
           }
          ]
         }
        },
        "required": [
         "coordinates"
        ]
       },
       {
        "type": "null"
       }
      ]
     },
     "locationId": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ]
     },
     "templateId": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ]
     },
     "memoryTemplateId": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ],
      "description": "DEPRECATED: use `templateId`. Kept for older client builds."
     },
     "recommendedTemplateIds": {
      "anyOf": [
       {
        "type": "array",
        "items": {
         "type": "string"
        }
       },
       {
        "type": "null"
       }
      ]
     },
     "calendarEventId": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ]
     },
     "updatedAt": {
      "type": "string"
     }
    },
    "required": [
     "id",
     "title",
     "summary",
     "content",
     "startTime",
     "endTime",
     "type",
     "keywords",
     "speakers",
     "memorySpeakers",
     "quotes",
     "location",
     "locationId",
     "templateId",
     "memoryTemplateId",
     "recommendedTemplateIds",
     "calendarEventId",
     "updatedAt"
    ]
   }
  },
  "nextCursor": {
   "anyOf": [
    {
     "type": "string"
    },
    {
     "type": "null"
    }
   ]
  }
 },
 "required": [
  "items",
  "nextCursor"
 ]
}
```

## POST /conversations

operationId: `conversations.create`

Request body:

```json
{
 "type": "object",
 "properties": {
  "startTime": {
   "type": "string",
   "description": "ISO 8601 start time of the conversation"
  },
  "calendarEventId": {
   "type": "string",
   "description": "Associated calendar event ID"
  },
  "templateId": {
   "type": "string",
   "description": "Memory template to apply"
  }
 },
 "required": [
  "startTime"
 ]
}
```

200 response schema:

```json
{
 "type": "object",
 "properties": {
  "id": {
   "type": "string",
   "description": "Created conversation ID"
  }
 },
 "required": [
  "id"
 ]
}
```

## GET /tasks

operationId: `tasks.list`

| param | in | required | schema |
|---|---|---|---|
| status | query | yes | enum: new/approved/completed/rejected/skipped/cancelled/expired, string |

200 response schema:

```json
{
 "type": "object",
 "properties": {
  "items": {
   "type": "array",
   "items": {
    "type": "object",
    "properties": {
     "id": {
      "type": "string"
     },
     "title": {
      "type": "string"
     },
     "date": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ]
     },
     "status": {
      "enum": [
       "new",
       "approved",
       "completed",
       "rejected",
       "skipped",
       "cancelled",
       "expired"
      ],
      "type": "string"
     },
     "memoryId": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ]
     },
     "completionDate": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ]
     },
     "cancellationDate": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ]
     }
    },
    "required": [
     "id",
     "title",
     "status"
    ]
   }
  }
 },
 "required": [
  "items"
 ]
}
```

## POST /tasks

operationId: `tasks.create`

Request body:

```json
{
 "type": "object",
 "properties": {
  "title": {
   "type": "string",
   "description": "Task title"
  },
  "date": {
   "type": "string",
   "description": "ISO 8601 due date"
  }
 },
 "required": [
  "title",
  "date"
 ]
}
```

200 response schema:

```json
{
 "type": "object",
 "properties": {
  "id": {
   "type": "string"
  },
  "title": {
   "type": "string"
  },
  "date": {
   "anyOf": [
    {
     "type": "string"
    },
    {
     "type": "null"
    }
   ]
  },
  "status": {
   "enum": [
    "new",
    "approved",
    "completed",
    "rejected",
    "skipped",
    "cancelled",
    "expired"
   ],
   "type": "string"
  },
  "memoryId": {
   "anyOf": [
    {
     "type": "string"
    },
    {
     "type": "null"
    }
   ]
  },
  "completionDate": {
   "anyOf": [
    {
     "type": "string"
    },
    {
     "type": "null"
    }
   ]
  },
  "cancellationDate": {
   "anyOf": [
    {
     "type": "string"
    },
    {
     "type": "null"
    }
   ]
  }
 },
 "required": [
  "id",
  "title",
  "status"
 ]
}
```

## DELETE /tasks/{id}

operationId: `tasks.delete`

| param | in | required | schema |
|---|---|---|---|
| id | path | yes | string |

Request body:

```json
{
 "type": "object",
 "properties": {},
 "required": []
}
```

200 response schema:

```json
{
 "type": "object",
 "properties": {
  "success": {
   "type": "boolean"
  }
 },
 "required": [
  "success"
 ]
}
```

## PATCH /tasks/{id}

operationId: `tasks.update`

| param | in | required | schema |
|---|---|---|---|
| id | path | yes | string |

Request body:

```json
{
 "type": "object",
 "properties": {
  "title": {
   "type": "string",
   "description": "Updated task title"
  },
  "date": {
   "type": "string",
   "description": "ISO 8601 due date"
  },
  "status": {
   "enum": [
    "new",
    "approved",
    "completed",
    "rejected",
    "skipped",
    "cancelled",
    "expired"
   ],
   "type": "string",
   "description": "Updated status"
  },
  "completionDate": {
   "type": "string",
   "description": "ISO 8601 completion date"
  },
  "cancellationDate": {
   "type": "string",
   "description": "ISO 8601 cancellation date"
  }
 },
 "required": []
}
```

200 response schema:

```json
{
 "type": "object",
 "properties": {
  "success": {
   "type": "boolean"
  },
  "task": {
   "anyOf": [
    {
     "type": "object",
     "properties": {
      "id": {
       "type": "string"
      },
      "title": {
       "type": "string"
      },
      "date": {
       "anyOf": [
        {
         "type": "string"
        },
        {
         "type": "null"
        }
       ]
      },
      "status": {
       "enum": [
        "new",
        "approved",
        "completed",
        "rejected",
        "skipped",
        "cancelled",
        "expired"
       ],
       "type": "string"
      },
      "memoryId": {
       "anyOf": [
        {
         "type": "string"
        },
        {
         "type": "null"
        }
       ]
      },
      "completionDate": {
       "anyOf": [
        {
         "type": "string"
        },
        {
         "type": "null"
        }
       ]
      },
      "cancellationDate": {
       "anyOf": [
        {
         "type": "string"
        },
        {
         "type": "null"
        }
       ]
      }
     },
     "required": [
      "id",
      "title",
      "status"
     ]
    },
    {
     "type": "null"
    }
   ]
  }
 },
 "required": [
  "success",
  "task"
 ]
}
```

## GET /transcriptions

operationId: `transcriptions.list`

| param | in | required | schema |
|---|---|---|---|
| startTime | query | yes | string |
| endTime | query | no | string |
| conversationId | query | no | string |
| recordingSource | query | no | enum: wearable/phone/desktop, string |
| limit | query | no | number, max=2000, min=1 |
| cursor | query | no | string |
| pageSize | query | no | number, max=1000, min=1 |
| order | query | no | enum: asc/desc, string, default=asc |
| inclusive | query | no | string, default=True |

200 response schema:

```json
{
 "type": "object",
 "properties": {
  "items": {
   "type": "array",
   "items": {
    "type": "object",
    "properties": {
     "id": {
      "type": "string"
     },
     "text": {
      "type": "string"
     },
     "timestamp": {
      "type": "string"
     },
     "speaker": {
      "type": "string"
     },
     "speakerProfileId": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ]
     },
     "start": {
      "type": "number"
     },
     "end": {
      "type": "number"
     },
     "createdAt": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ]
     },
     "source": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ]
     },
     "recordingSource": {
      "anyOf": [
       {
        "enum": [
         "wearable",
         "phone",
         "desktop"
        ],
        "type": "string"
       },
       {
        "type": "null"
       }
      ]
     }
    },
    "required": [
     "id",
     "text",
     "timestamp",
     "speaker",
     "speakerProfileId",
     "start",
     "end",
     "createdAt",
     "source",
     "recordingSource"
    ]
   }
  },
  "nextCursor": {
   "anyOf": [
    {
     "type": "string"
    },
    {
     "type": "null"
    }
   ]
  }
 },
 "required": [
  "items",
  "nextCursor"
 ]
}
```

## GET /speaker-profiles

operationId: `speakerProfiles.list`

200 response schema:

```json
{
 "type": "object",
 "properties": {
  "items": {
   "type": "array",
   "items": {
    "type": "object",
    "properties": {
     "id": {
      "type": "string"
     },
     "name": {
      "type": "string"
     },
     "color": {
      "type": "string"
     },
     "createdAt": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ]
     },
     "updatedAt": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ]
     }
    },
    "required": [
     "id",
     "name",
     "color",
     "createdAt",
     "updatedAt"
    ]
   }
  }
 },
 "required": [
  "items"
 ]
}
```

## POST /speaker-profiles

operationId: `speakerProfiles.create`

Request body:

```json
{
 "type": "object",
 "properties": {
  "name": {
   "type": "string",
   "description": "Speaker name"
  },
  "color": {
   "type": "string",
   "description": "Display color hex code"
  }
 },
 "required": [
  "name",
  "color"
 ]
}
```

200 response schema:

```json
{
 "type": "object",
 "properties": {
  "id": {
   "type": "string"
  }
 },
 "required": [
  "id"
 ]
}
```

## DELETE /speaker-profiles/{id}

operationId: `speakerProfiles.delete`

| param | in | required | schema |
|---|---|---|---|
| id | path | yes | string |

Request body:

```json
{
 "type": "object",
 "properties": {},
 "required": []
}
```

200 response schema:

```json
{
 "type": "object",
 "properties": {
  "success": {
   "type": "boolean"
  }
 },
 "required": [
  "success"
 ]
}
```

## GET /speaker-profiles/{id}

operationId: `speakerProfiles.get`

| param | in | required | schema |
|---|---|---|---|
| id | path | yes | string |

200 response schema:

```json
{
 "anyOf": [
  {
   "type": "object",
   "properties": {
    "id": {
     "type": "string"
    },
    "name": {
     "type": "string"
    },
    "color": {
     "type": "string"
    },
    "createdAt": {
     "anyOf": [
      {
       "type": "string"
      },
      {
       "type": "null"
      }
     ]
    },
    "updatedAt": {
     "anyOf": [
      {
       "type": "string"
      },
      {
       "type": "null"
      }
     ]
    }
   },
   "required": [
    "id",
    "name",
    "color",
    "createdAt",
    "updatedAt"
   ]
  },
  {
   "type": "null"
  }
 ]
}
```

## PATCH /speaker-profiles/{id}

operationId: `speakerProfiles.update`

| param | in | required | schema |
|---|---|---|---|
| id | path | yes | string |

Request body:

```json
{
 "type": "object",
 "properties": {
  "name": {
   "type": "string",
   "description": "Updated name"
  },
  "color": {
   "type": "string",
   "description": "Updated color hex code"
  }
 },
 "required": []
}
```

200 response schema:

```json
{
 "type": "object",
 "properties": {
  "success": {
   "type": "boolean"
  }
 },
 "required": [
  "success"
 ]
}
```

## GET /memory-templates

operationId: `memoryTemplates.list`

200 response schema:

```json
{
 "type": "object",
 "properties": {
  "items": {
   "type": "array",
   "items": {
    "type": "object",
    "properties": {
     "id": {
      "type": "string"
     },
     "title": {
      "type": "string"
     },
     "prompt": {
      "type": "string"
     },
     "description": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ]
     },
     "emoji": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ]
     },
     "sections": {
      "type": "array",
      "items": {
       "type": "object",
       "properties": {
        "title": {
         "type": "string"
        },
        "prompt": {
         "type": "string"
        }
       },
       "required": [
        "title",
        "prompt"
       ]
      }
     },
     "createdAt": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ]
     },
     "updatedAt": {
      "anyOf": [
       {
        "type": "string"
       },
       {
        "type": "null"
       }
      ]
     }
    },
    "required": [
     "id",
     "title",
     "prompt",
     "description",
     "emoji",
     "sections",
     "createdAt",
     "updatedAt"
    ]
   }
  }
 },
 "required": [
  "items"
 ]
}
```

## POST /memory-templates

operationId: `memoryTemplates.create`

Request body:

```json
{
 "type": "object",
 "properties": {
  "title": {
   "type": "string",
   "description": "Template title"
  },
  "prompt": {
   "type": "string",
   "description": "Main AI prompt for the template"
  },
  "description": {
   "type": "string",
   "description": "Human-readable description"
  },
  "emoji": {
   "type": "string",
   "description": "Emoji icon for the template"
  },
  "sections": {
   "type": "array",
   "items": {
    "type": "object",
    "properties": {
     "title": {
      "type": "string"
     },
     "prompt": {
      "type": "string"
     }
    },
    "required": [
     "title",
     "prompt"
    ]
   },
   "description": "Template sections"
  }
 },
 "required": [
  "title",
  "prompt",
  "emoji",
  "sections"
 ]
}
```

200 response schema:

```json
{
 "type": "object",
 "properties": {
  "id": {
   "type": "string"
  },
  "title": {
   "type": "string"
  },
  "prompt": {
   "type": "string"
  },
  "description": {
   "anyOf": [
    {
     "type": "string"
    },
    {
     "type": "null"
    }
   ]
  },
  "emoji": {
   "anyOf": [
    {
     "type": "string"
    },
    {
     "type": "null"
    }
   ]
  },
  "sections": {
   "type": "array",
   "items": {
    "type": "object",
    "properties": {
     "title": {
      "type": "string"
     },
     "prompt": {
      "type": "string"
     }
    },
    "required": [
     "title",
     "prompt"
    ]
   }
  },
  "createdAt": {
   "anyOf": [
    {
     "type": "string"
    },
    {
     "type": "null"
    }
   ]
  },
  "updatedAt": {
   "anyOf": [
    {
     "type": "string"
    },
    {
     "type": "null"
    }
   ]
  }
 },
 "required": [
  "id",
  "title",
  "prompt",
  "description",
  "emoji",
  "sections",
  "createdAt",
  "updatedAt"
 ]
}
```

## DELETE /memory-templates/{id}

operationId: `memoryTemplates.delete`

| param | in | required | schema |
|---|---|---|---|
| id | path | yes | string |

Request body:

```json
{
 "type": "object",
 "properties": {},
 "required": []
}
```

200 response schema:

```json
{
 "type": "object",
 "properties": {
  "success": {
   "type": "boolean"
  }
 },
 "required": [
  "success"
 ]
}
```

## GET /memory-templates/{id}

operationId: `memoryTemplates.get`

| param | in | required | schema |
|---|---|---|---|
| id | path | yes | string |

200 response schema:

```json
{
 "type": "object",
 "properties": {
  "id": {
   "type": "string"
  },
  "title": {
   "type": "string"
  },
  "prompt": {
   "type": "string"
  },
  "description": {
   "anyOf": [
    {
     "type": "string"
    },
    {
     "type": "null"
    }
   ]
  },
  "emoji": {
   "anyOf": [
    {
     "type": "string"
    },
    {
     "type": "null"
    }
   ]
  },
  "sections": {
   "type": "array",
   "items": {
    "type": "object",
    "properties": {
     "title": {
      "type": "string"
     },
     "prompt": {
      "type": "string"
     }
    },
    "required": [
     "title",
     "prompt"
    ]
   }
  },
  "createdAt": {
   "anyOf": [
    {
     "type": "string"
    },
    {
     "type": "null"
    }
   ]
  },
  "updatedAt": {
   "anyOf": [
    {
     "type": "string"
    },
    {
     "type": "null"
    }
   ]
  }
 },
 "required": [
  "id",
  "title",
  "prompt",
  "description",
  "emoji",
  "sections",
  "createdAt",
  "updatedAt"
 ]
}
```

## PATCH /memory-templates/{id}

operationId: `memoryTemplates.update`

| param | in | required | schema |
|---|---|---|---|
| id | path | yes | string |

Request body:

```json
{
 "type": "object",
 "properties": {
  "title": {
   "type": "string",
   "description": "Updated title"
  },
  "prompt": {
   "type": "string",
   "description": "Updated AI prompt"
  },
  "description": {
   "type": "string",
   "description": "Updated description"
  },
  "emoji": {
   "type": "string",
   "description": "Updated emoji"
  },
  "sections": {
   "type": "array",
   "items": {
    "type": "object",
    "properties": {
     "title": {
      "type": "string"
     },
     "prompt": {
      "type": "string"
     }
    },
    "required": [
     "title",
     "prompt"
    ]
   },
   "description": "Updated sections"
  }
 },
 "required": []
}
```

200 response schema:

```json
{
 "type": "object",
 "properties": {
  "success": {
   "type": "boolean"
  }
 },
 "required": [
  "success"
 ]
}
```

## GET /user/me

operationId: `user.get`

200 response schema:

```json
{
 "type": "object",
 "properties": {
  "email": {
   "type": "string",
   "description": "User email address"
  }
 },
 "required": [
  "email"
 ]
}
```

## GET /sharables

operationId: `sharables.list`

| param | in | required | schema |
|---|---|---|---|
| conversationId | query | yes | string |

200 response schema:

```json
{
 "type": "object",
 "properties": {
  "items": {
   "type": "array",
   "items": {
    "type": "object",
    "properties": {
     "id": {
      "type": "string",
      "description": "Sharable ID"
     },
     "sharedFields": {
      "type": "array",
      "items": {
       "type": "string"
      },
      "description": "Fields included in the share"
     },
     "authorName": {
      "type": "string",
      "description": "Display name of the sharer"
     },
     "enabled": {
      "type": "boolean",
      "description": "Whether the share link is active"
     },
     "url": {
      "type": "string",
      "description": "Fully constructed sharable URL"
     }
    },
    "required": [
     "id",
     "sharedFields",
     "authorName",
     "enabled",
     "url"
    ]
   }
  }
 },
 "required": [
  "items"
 ]
}
```

## POST /sharables

operationId: `sharables.create`

Request body:

```json
{
 "type": "object",
 "properties": {
  "authorName": {
   "type": "string",
   "description": "Display name of the author"
  },
  "sharedFields": {
   "type": "array",
   "items": {
    "type": "string"
   },
   "description": "Fields from the memory to include in the share"
  },
  "targetDocId": {
   "type": "string",
   "description": "ID of the memory to share"
  }
 },
 "required": [
  "authorName",
  "sharedFields",
  "targetDocId"
 ]
}
```

200 response schema:

```json
{
 "type": "object",
 "properties": {
  "id": {
   "type": "string",
   "description": "ID of the created sharable link"
  },
  "url": {
   "type": "string",
   "description": "Fully constructed sharable URL"
  }
 },
 "required": [
  "id",
  "url"
 ]
}
```

## DELETE /sharables/{id}

operationId: `sharables.delete`

| param | in | required | schema |
|---|---|---|---|
| id | path | yes | string |

Request body:

```json
{
 "type": "object",
 "properties": {},
 "required": []
}
```

200 response schema:

```json
{
 "type": "object",
 "properties": {
  "success": {
   "type": "boolean"
  }
 },
 "required": [
  "success"
 ]
}
```

## PATCH /sharables/{id}

operationId: `sharables.update`

| param | in | required | schema |
|---|---|---|---|
| id | path | yes | string |

Request body:

```json
{
 "type": "object",
 "properties": {
  "authorName": {
   "type": "string",
   "description": "Updated display name of the author"
  },
  "sharedFields": {
   "type": "array",
   "items": {
    "type": "string"
   },
   "description": "Updated fields from the memory to include in the share"
  },
  "enabled": {
   "type": "boolean",
   "description": "Whether the share link is active"
  }
 },
 "required": []
}
```

200 response schema:

```json
{
 "type": "object",
 "properties": {
  "id": {
   "type": "string",
   "description": "Sharable ID"
  },
  "sharedFields": {
   "type": "array",
   "items": {
    "type": "string"
   },
   "description": "Fields included in the share"
  },
  "authorName": {
   "type": "string",
   "description": "Display name of the sharer"
  },
  "enabled": {
   "type": "boolean",
   "description": "Whether the share link is active"
  },
  "url": {
   "type": "string",
   "description": "Fully constructed sharable URL"
  }
 },
 "required": [
  "id",
  "sharedFields",
  "authorName",
  "enabled",
  "url"
 ]
}
```

## GET /sharables/resolve

operationId: `sharables.resolve`

| param | in | required | schema |
|---|---|---|---|
| idOrUrl | query | yes | string |

200 response schema:

```json
{
 "anyOf": [
  {
   "type": "object",
   "properties": {
    "found": {
     "const": false
    },
    "error": {
     "type": "string",
     "description": "Machine-readable error code"
    },
    "hint": {
     "type": "string",
     "description": "Human-readable hint on how to proceed"
    }
   },
   "required": [
    "found",
    "error",
    "hint"
   ]
  },
  {
   "type": "object",
   "properties": {
    "found": {
     "const": true
    },
    "share": {
     "type": "object",
     "properties": {
      "id": {
       "type": "string",
       "description": "Sharable ID"
      },
      "url": {
       "type": "string",
       "description": "Fully constructed sharable URL"
      },
      "authorName": {
       "type": "string",
       "description": "Display name of the sharer"
      },
      "sharedFields": {
       "type": "array",
       "items": {
        "type": "string"
       },
       "description": "Fields included in the share"
      },
      "target": {
       "type": "object",
       "properties": {
        "title": {
         "type": "string"
        },
        "startTime": {
         "type": "string"
        },
        "endTime": {
         "type": "string"
        },
        "summary": {
         "type": "string"
        },
        "content": {
         "type": "string"
        },
        "keywords": {
         "type": "array",
         "items": {
          "type": "string"
         }
        },
        "location": {
         "anyOf": [
          {
           "type": "object",
           "properties": {
            "address": {
             "type": "string"
            },
            "coordinates": {
             "type": "object",
             "properties": {
              "_latitude": {
               "type": "number"
              },
              "_longitude": {
               "type": "number"
              }
             },
             "required": [
              "_latitude",
              "_longitude"
             ]
            },
            "country": {
             "type": "string"
            },
            "zip": {
             "type": "string"
            }
           },
           "required": [
            "address",
            "coordinates"
           ],
           "additionalProperties": {}
          },
          {
           "type": "null"
          }
         ]
        },
        "quotes": {
         "type": "array",
         "items": {
          "type": "object",
          "properties": {
           "text": {
            "type": "string"
           },
           "context": {
            "anyOf": [
             {
              "type": "string"
             },
             {
              "type": "null"
             }
            ]
           }
          },
          "required": [
           "text",
           "context"
          ],
          "additionalProperties": {}
         }
        },
        "transcriptions": {
         "type": "array",
         "items": {
          "type": "object",
          "properties": {
           "speaker": {
            "type": "string"
           },
           "text": {
            "type": "string"
           },
           "timestamp": {
            "type": "string"
           },
           "created": {
            "type": "string"
           }
          },
          "required": [
           "text"
          ],
          "additionalProperties": {}
         }
        }
       },
       "additionalProperties": {},
       "description": "The shared memory content, limited to sharedFields"
      }
     },
     "required": [
      "id",
      "url",
      "authorName",
      "sharedFields",
      "target"
     ]
    },
    "isOwn": {
     "type": "boolean",
     "description": "Whether the underlying memory belongs to the requesting user"
    },
    "conversationId": {
     "type": "string",
     "description": "Underlying conversation id \u2014 only present when isOwn"
    }
   },
   "required": [
    "found",
    "share",
    "isOwn"
   ]
  }
 ]
}
```
